#!/bin/bash

docker stop seita-pg
docker rm seita-pg
docker build -t seita-pg:latest .
