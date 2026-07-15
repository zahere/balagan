FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml LICENSE README.md ./
COPY src ./src
COPY configs ./configs
COPY data ./data

RUN pip install --no-cache-dir .

# NOTE: nothing is persisted inside this container. On Nebius Serverless the
# job VM's filesystem is released with the job, so the checkpoint MUST go to
# Object Storage — pass S3_BUCKET / S3_PREFIX / S3_ENDPOINT_URL / AWS_* via
# `nebius ai job create --env`. See nebius/RUNBOOK.md.
ENTRYPOINT ["balagan"]
CMD ["run", "--config", "configs/demo.yaml"]
