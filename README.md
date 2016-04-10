# Hopps

Hopps is a PoC security scanner for AWS. The port scan is run from Lambda via
a scheduled event. Any EC2 instances in the same AWS account with public IPs
will be port scanned and the results compared to a list of expectations
(configured via a JSON file on S3). Results are published to a CloudWatch
Metric, from which you can trigger any alerting you wish.

## Using Hopps

### Configuring Virtualenv

Until hopps is in pypi, you must set up a virtualenv to use it. Here's how:

    virtualenv venv
    . ./venv/bin/activate
    pip install -r requirements.txt

### Interactive Use

In addition to being run from Lambda, Hopps can also be run from the command
line. This is useful for development and debugging.

Example:

    $ ./hopps/main.py -h
    ...
    $ ./hopps/main.py
    2016-04-10 12:35:45,351 main.py:44: argv: ['./hopps/main.py']
    2016-04-10 12:35:45,352 main.py:115: Configuration: Namespace(cloudwatch_metric='NumUnexpectedPortsOpen', cloudwatch_namespace='Hopps', config=None, parallelism=32, ports='20-22,25,42,53,80,123,143,389,443,993,995,3306,4040,4041,4443,5900-5906,7077,8080,8081,18040', timeout=240)
    2016-04-10 12:35:45,367 credentials.py:611: Found credentials in shared credentials file: ~/.aws/credentials
    2016-04-10 12:35:45,444 collection.py:152: Calling paginated ec2:describe_instances with {'Filters': [{'Values': ['running'], 'Name': 'instance-state-name'}]}
    2016-04-10 12:35:45,447 connectionpool.py:735: Starting new HTTPS connection (1): ec2.us-west-2.amazonaws.com
    2016-04-10 12:35:45,712 main.py:118: Found public IPs: ['52.25.73.85']
    2016-04-10 12:35:45,712 main.py:121: Scanning 28 ip:port pairs.
    2016-04-10 12:35:46,719 main.py:140: Found 1 open ports.
    2016-04-10 12:35:46,719 main.py:144: == UNEXPECTED ==
    2016-04-10 12:35:46,719 main.py:146: 52.25.73.85:22
    2016-04-10 12:35:46,719 main.py:149: Found 1 unexpected open ports.
    2016-04-10 12:35:46,724 main.py:188: Hopps/NumUnexpectedPortsOpen=1
    2016-04-10 12:35:46,726 connectionpool.py:735: Starting new HTTPS connection (1): monitoring.us-west-2.amazonaws.com

### Deploying Hopps to Lambda

This process has only been tested on Linux.

#### Create Deployment .zip

    ./build.sh
    ls -lh out/deploy.zip

#### Creating a deploy bucket

This step is optional if you already have a bucket suitable for holding Lambda deployment artifacts.

    aws s3 --region us-west-2 mb hopps-deploy-bucket

`deploy.sh` is a simple helper to copy the deployment zip to the bucket:

    REGION=us-west-2 BUCKET=hopps-deploy-bucket ./deploy.sh

#### Creating the CloudFormation stack

Replace `hopps-deploy-bucket` with the name of your deployment bucket.

    aws cloudformation update-stack \
      --capabilities CAPABILITY_IAM \
      --stack-name hopps \
      --template-body file://./cloudformation/hopps.template \
      --parameters \
        ParameterKey=DeployS3Bucket,ParameterValue=hopps-deploy-bucket \
        ParameterKey=DeployS3Key,ParameterValue=hopps/latest.zip

#### Configuring Hopps

Hopps only supports simple TCP scans for now. Expectations must be stated
with IP addresses (not hostnames) and port numbers. Here's an example:

    {
      "argv": [],
      "expectations": {
        "open": [
          [
            "52.89.236.85",
            "443"
          ],
          [
            "52.25.73.85",
            "22"
          ]
        ]
      }
    }

Expectations are specified in a JSON file. For interactive use, you can refer to the
config file with a command line flag. Example:

    ./hopps/main.py --config hopps-config.json

When running under Lambda, the configuration is stored on an S3 bucket
that the CloudFormation stack creates for you. You are responsible for creating the
config file and copying it to the config bucket before the Lambda function will be run.
The CloudFormation stack's `BucketName` output parameter will tell you where to write
the config file. You can get this from the AWS Lambda Console or via the command line.
Here's an example of how to get the bucket name from the command line and to copy the
configuration there:

    aws cloudformation describe-stacks \
      --stack-name hopps \
      --query Stacks[0].Outputs
    ...
    aws s3 cp hopps-config.json s3://${BUCKET}/

#### Creating Scheduled Event

AWS does not currently offer an API for creating the scheduled event. You can
create one using the AWS Lambda Console by following these steps:

1. Log in to the AWS Console and navigate to the CloudWatch service.
2. Click "Events".
3. Click "Create Rule".
4. In "Event Selector" dropdown, select "Schedule". To run hourly, select a
fixed rate of 1 hours.
5. Click "Add Target".
6. Select the name of the Lambda function from the dropdown.
7. Click "Configure details"
8. Give the schedule a name and click "Create Rule".

#### View Logs

AWS Lambda records all results to CloudWatch Logs. In the AWS CloudWatch Console, select "Logs" and navigate to the
logs for the Hopps lambda function.


