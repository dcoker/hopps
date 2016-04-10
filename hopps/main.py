#!/usr/bin/env python
# coding=utf-8
"""
Scans public IPs of an AWS account to detect ports that are open unexpectedly.
"""
import argparse
import itertools
import json
import logging
import random
import resource
import signal
import sys
import urlparse
from collections import namedtuple

import boto3
import gevent
import gevent.pool
from botocore.config import Config
from gevent import socket

HostPort = namedtuple('HostPort', ['host', 'port'])


def lambda_main(event, context):
    logging.getLogger().setLevel(logging.INFO)
    logging.info("Event: %r" % event)
    # Extract the name of the S3 bucket containing the configuration file from the Description
    # of this lambda function.
    lambda_api = boto3.client('lambda')
    func = lambda_api.get_function(FunctionName=context.function_name)
    description = func['Configuration']['Description']
    json_portion = description[description.find("{"):]
    bucket = json.loads(json_portion)["ConfigBucket"]
    config_path = "s3://%s/hopps-config.json" % bucket
    logging.info("Reading config from %s" % config_path)
    argv, expectations = read_config(config_path)
    start_scanning(create_argparser().parse_args(argv), expectations)


def cli_main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(filename)s:%(lineno)d: %(message)s')
    logging.info("argv: %r" % (sys.argv,))
    args = create_argparser().parse_args()
    _, expectations = read_config(args.config)
    start_scanning(args, expectations)


def read_config(filename):
    if not filename:
        return [], set([])

    if filename.startswith("s3:"):
        contents = get_expected_open_ports_s3(filename)
    else:
        contents = open(filename, "r").read()

    configuration = {"expectations": {"open": []}, "argv": []}
    configuration.update(json.loads(contents))
    return configuration["argv"], set([
                                          HostPort(str(x), int(y))
                                          for x, y in configuration["expectations"]["open"]])


def get_expected_open_ports_s3(filename):
    parsed = urlparse.urlparse(filename)
    s3 = boto3.client("s3")
    # boto seems unhappy to GetObjecct w/o providing a bucket region
    region = s3.get_bucket_location(Bucket=parsed.netloc)["LocationConstraint"]
    if not region:  # Per docs, None means us-standard
        region = 'us-east-1'
    # use path-style addressing to support buckets with . in the name
    get_object_response = boto3.client(
        's3',
        region_name=region,
        config=Config(s3={'addressing_style': 'path'})).get_object(
        Bucket=parsed.netloc, Key=parsed.path.lstrip('/'))
    contents = get_object_response["Body"].read()
    return contents


def create_argparser():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--ports',
                        default='20-22,25,42,53,80,123,143,389,443,993,995,'
                                '3306,4040,4041,4443,5900-5906,7077,8080,'
                                '8081,18040',
                        help='The TCP port numbers to scan. Example: "1-1024,18080"')
    parser.add_argument('--timeout',
                        default=240,
                        type=int,
                        help='Maximum time the port scanner is allowed to run (in seconds).')
    parser.add_argument('--parallelism',
                        default=min(32, resource.getrlimit(resource.RLIMIT_NOFILE)[0] / 2),
                        type=int,
                        help='Maximum number of sockets to attempt to open at once. Lambda limits open FDs and '
                             'threads to 1024, but this value should be much lower.')
    parser.add_argument('--config',
                        default=None,
                        help='Path to JSON file defining expected open ip:port pairs. This may be an s3:// '
                             'path. Example file contents: {"argv": [], "expectations":{"open":["192.231.42.1:53"]}}')
    parser.add_argument('--cloudwatch-namespace',
                        default="Hopps",
                        help='The name of the CloudWatch namespace to report to.')
    parser.add_argument('--cloudwatch-metric',
                        default="NumUnexpectedPortsOpen",
                        help='The name of the CloudWatch metric for reporting number of unexpected open ports.')
    return parser


def start_scanning(args, expectations):
    gevent.signal(signal.SIGQUIT, gevent.kill)  # paranoia: ensure gevent respects sigquit
    logging.info("Configuration: %r" % (args,))
    ports_to_scan = parse_port_ranges(args.ports)
    public_ips = list(find_public_ips())
    logging.info("Found public IPs: %r" % public_ips)
    ip_port_pairs = [HostPort(x, y) for x, y in itertools.product(public_ips, ports_to_scan)]
    random.shuffle(ip_port_pairs)
    logging.info("Scanning %d ip:port pairs." % (len(ip_port_pairs)))

    open_ports_collector = pooled_port_scan(args, ip_port_pairs)

    num_unexpected = print_results(expectations, open_ports_collector)
    report_to_cloudwatch(args.cloudwatch_namespace, args.cloudwatch_metric, num_unexpected)


def pooled_port_scan(args, ip_port_pairs):
    open_ports_collector = []
    jobs = gevent.pool.Pool(args.parallelism)
    with gevent.Timeout(args.timeout, False):
        for ip_port_pair in ip_port_pairs:
            jobs.spawn(scan_one_port, ip_port_pair, open_ports_collector)
        jobs.join()
    return open_ports_collector


def print_results(expectations, open_ports_collector):
    logging.info("Found %d open ports." % len(open_ports_collector))
    num_unexpected = 0
    for is_expected, hpps in itertools.groupby(sorted(open_ports_collector, expectations.__contains__),
                                               expectations.__contains__):
        logging.info("== %s ==" % ("EXPECTED" if is_expected else "UNEXPECTED"))
        for hpp in hpps:
            logging.info("%s:%s" % (hpp[0], hpp[1]))
            if not is_expected:
                num_unexpected += 1
    logging.info("Found %d unexpected open ports." % num_unexpected)
    return num_unexpected


def scan_one_port(target, open_ports):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)  # hack
        sock.connect(target)
        open_ports.append(target)
    except socket.timeout:
        pass
    except socket.error, e:
        if e.errno not in (111,):  # refused
            raise
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except:
            pass
        sock.close()


def parse_port_ranges(spec):
    # http://stackoverflow.com/questions/5704931/parse-string-of-integer-sets-with-intervals-to-list
    ranges = (x.split("-") for x in spec.split(","))
    return (i for r in ranges for i in range(int(r[0]), int(r[-1]) + 1))


def find_public_ips():
    ec2 = boto3.resource("ec2")
    instances = ec2.instances.filter(Filters=[
        {'Name': 'instance-state-name', 'Values': ['running']}
    ])
    return (i.public_ip_address for i in instances if i.public_ip_address)


def report_to_cloudwatch(cloudwatch_namespace, cloudwatch_metric, num_unexpected):
    cloudwatch = boto3.client("cloudwatch")
    logging.info("%s/%s=%s" % (cloudwatch_namespace, cloudwatch_metric, num_unexpected))
    cloudwatch.put_metric_data(Namespace=cloudwatch_namespace,
                               MetricData=[{
                                   'MetricName': cloudwatch_metric,
                                   'Value': num_unexpected,
                                   'Unit': 'Count'}])


if __name__ == "__main__":
    cli_main()
