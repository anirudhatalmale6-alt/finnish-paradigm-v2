#!/usr/bin/env bash
set -e
curl -f http://localhost:8000/api/health
curl -f http://localhost:8000/api/courses
echo "Smoke test passed"
