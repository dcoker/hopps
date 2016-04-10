#!/bin/bash -x
set -e
top=$(pwd)
rm -fr out || /bin/true
mkdir -p out
zip out/deploy.zip lambda_main.py hopps/*
cd venv/lib/python2.7/site-packages 
zip -r ${top}/out/deploy.zip . -x boto\* pip\*
