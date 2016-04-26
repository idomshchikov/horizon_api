#!/usr/bin/env bash

psql -h localhost -c "drop database horizondb;"
psql -h localhost -c "create database horizondb;"
python -c "import horizon_api as h; h.create_templates()"