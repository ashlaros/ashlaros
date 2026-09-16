"""The R2 client, in one place.

Four scripts built their own from the same four environment variables, and
the copies drifted: upload_iso.py grew a 900-second read timeout after a
1.7 GB copy failed the build with "Read timeout on .../latest/ashlaros.iso"
- the copy had started, only the client gave up waiting - while the three
that also move large objects kept botocore's 60-second default. publish.py
uploads packages of 139 MiB as a single PUT, which is the same failure
waiting for a slow runner.

So the timeout belongs to the client, not to one caller of it.
"""

import os
import sys

import boto3
from botocore.config import Config

# Long enough for R2 to finish a multi-hundred-megabyte transfer or a
# server-side copy of a whole ISO, short enough to fail a genuinely dead
# connection within a CI job's patience. Retries cover the transient case;
# they do not help when the client hangs up mid-transfer, which is what the
# read timeout decides.
R2_CONFIG = Config(
    read_timeout=900,
    connect_timeout=60,
    retries={"max_attempts": 3},
)


def log(message: str) -> None:
    """Progress on stderr, so stdout stays whatever the script emits."""
    print(message, file=sys.stderr, flush=True)


def s3_client():
    """A client for the R2 bucket, configured from the environment."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=R2_CONFIG,
    )
