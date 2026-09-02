#!/bin/sh
set -eu

BUCKET="${GARAGE_BUCKET:-ch.so.daten}"
ENDPOINT="${AWS_ENDPOINT_URL:-http://garage:3900}"
REGION="${AWS_DEFAULT_REGION:-garage}"

aws_call() {
  aws --endpoint-url "$ENDPOINT" --region "$REGION" "$@"
}

echo "Waiting for Garage S3 API at ${ENDPOINT} ..."
i=0
until aws_call s3api list-buckets >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 90 ]; then
    echo "Garage S3 API did not become ready." >&2
    exit 1
  fi
  sleep 1
done

echo "Ensuring bucket ${BUCKET} exists ..."
if ! aws_call s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws_call s3api create-bucket --bucket "$BUCKET" >/dev/null || true
fi

i=0
until aws_call s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "Bucket ${BUCKET} did not become available." >&2
    exit 1
  fi
  sleep 1
done

echo "Configuring public website access and CORS ..."
aws_call s3api put-bucket-website \
  --bucket "$BUCKET" \
  --website-configuration file:///init/website.json

aws_call s3api put-bucket-cors \
  --bucket "$BUCKET" \
  --cors-configuration file:///init/cors.json

echo "Garage initialization completed for bucket ${BUCKET}."
echo "Public object URL prefix: http://localhost:${GARAGE_PUBLIC_PORT:-8081}/${BUCKET}/"
