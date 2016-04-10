#!/usr/bin/env python
"""
Entrypoint for the Lambda function.
"""
from hopps.main import lambda_main as real_lambda_main


def lambda_main(event, context):
    return real_lambda_main(event, context)
