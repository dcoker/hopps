#!/bin/bash -x
set -e
REGION=${REGION:-us-west-2}
if [[ ! -n "${BUCKET}" ]]; then
  echo please set the BUCKET environment variable.
  exit 2
fi
name=$(basename $(pwd))
if [[ ! -e out/deploy.zip ]]; then
  echo the out/deploy.zip file does not exist. run build.sh first.
  exit 2
fi
ls -lh out/deploy.zip
aws --region ${REGION} s3 cp --acl public-read out/deploy.zip s3://${BUCKET}/${name}/latest.zip
