#!/usr/bin/env python3
"""Idempotently manage XiaoR's TOS historical-version retention rule."""

from __future__ import annotations

import os
import sys

import tos
from tos.enum import StatusType
from tos.exceptions import TosServerError
from tos.models2 import (
    BucketLifeCycleAbortInCompleteMultipartUpload,
    BucketLifeCycleNoCurrentVersionExpiration,
    BucketLifeCycleRule,
)


RULE_ID = "xiaor-release-retention-v1"
CONFIRMATION = "APPLY-XIAOR-TOS-LIFECYCLE"
NONCURRENT_DAYS = 30
MULTIPART_DAYS = 7


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def main() -> int:
    try:
        if required_env("TOS_LIFECYCLE_CONFIRM") != CONFIRMATION:
            raise ValueError("exact lifecycle confirmation value is required")

        bucket = required_env("TOS_BUCKET")
        client = tos.TosClientV2(
            required_env("TOS_ACCESS_KEY_ID"),
            required_env("TOS_SECRET_ACCESS_KEY"),
            required_env("TOS_ENDPOINT"),
            required_env("TOS_REGION"),
            security_token=os.environ.get("TOS_SECURITY_TOKEN") or None,
        )

        try:
            existing = list(client.get_bucket_lifecycle(bucket=bucket).rules or [])
        except TosServerError as exc:
            if exc.status_code != 404:
                raise
            existing = []

        preserved = [rule for rule in existing if rule.id != RULE_ID]
        managed_rule = BucketLifeCycleRule(
            id=RULE_ID,
            prefix="",
            status=StatusType.Status_Enable,
            no_current_version_expiration=BucketLifeCycleNoCurrentVersionExpiration(
                no_current_days=NONCURRENT_DAYS
            ),
            abort_in_complete_multipart_upload=BucketLifeCycleAbortInCompleteMultipartUpload(
                days_after_init=MULTIPART_DAYS
            ),
        )

        print("preserving lifecycle rules:", [rule.id for rule in preserved])
        client.put_bucket_lifecycle(bucket=bucket, rules=preserved + [managed_rule])

        result = client.get_bucket_lifecycle(bucket=bucket)
        matches = [rule for rule in result.rules or [] if rule.id == RULE_ID]
        if len(matches) != 1:
            raise RuntimeError("managed lifecycle rule was not returned exactly once")
        rule = matches[0]
        if (
            rule.status != StatusType.Status_Enable
            or rule.prefix != ""
            or rule.no_current_version_expiration is None
            or rule.no_current_version_expiration.no_current_days != NONCURRENT_DAYS
            or rule.abort_in_complete_multipart_upload is None
            or rule.abort_in_complete_multipart_upload.days_after_init != MULTIPART_DAYS
        ):
            raise RuntimeError("managed lifecycle rule verification failed")

        print(
            f"verified {RULE_ID}: noncurrent={NONCURRENT_DAYS} days, "
            f"incomplete-multipart={MULTIPART_DAYS} days"
        )
        return 0
    except (OSError, RuntimeError, TosServerError, ValueError) as exc:
        print(f"lifecycle maintenance failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

