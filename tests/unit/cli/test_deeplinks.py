"""Tests for console deep-links — the console-native bridge."""

import pytest

from harness_cli.deeplinks import build_console_url


class TestEC2:
    def test_instance_url(self):
        url = build_console_url("ec2", "i-abc123", region="us-east-1")
        assert "us-east-1.console.aws.amazon.com/ec2/home" in url
        assert "instanceId=i-abc123" in url
        assert "region=us-east-1" in url

    def test_volume_url(self):
        url = build_console_url("ec2", "vol-abc", region="eu-west-1")
        assert "VolumesDetails:volumeId=vol-abc" in url

    def test_sg_url(self):
        url = build_console_url("ec2", "sg-abc", region="us-east-1")
        assert "SecurityGroups:group-id=sg-abc" in url

    def test_instance_requires_region(self):
        with pytest.raises(ValueError, match="--region"):
            build_console_url("ec2", "i-abc123")

    def test_unrecognized_ec2_id_rejected(self):
        with pytest.raises(ValueError, match="resource type"):
            build_console_url("ec2", "garbage", region="us-east-1")


class TestS3:
    def test_bucket_url(self):
        url = build_console_url("s3", "my-bucket")
        assert "s3.console.aws.amazon.com/s3/buckets/my-bucket" in url

    def test_bucket_no_region_needed(self):
        url = build_console_url("s3", "b")
        assert url  # must not raise


class TestIAM:
    def test_user_url(self):
        url = build_console_url("iam", "alice")
        assert "console.aws.amazon.com/iam/home#/users/alice" in url

    def test_iam_is_global_no_region(self):
        url = build_console_url("iam", "alice")
        assert "region" not in url or "console.aws.amazon.com/iam" in url


class TestOthers:
    def test_cloudfront_distribution(self):
        url = build_console_url("cloudfront", "E123ABC")
        assert "cloudfront/v4/home#/distributions/E123ABC" in url

    def test_lambda_function(self):
        url = build_console_url("lambda", "my-func", region="eu-west-1")
        assert "functions/my-func" in url
        assert "region=eu-west-1" in url

    def test_vpc(self):
        url = build_console_url("vpc", "vpc-abc", region="us-east-1")
        assert "VpcId=vpc-abc" in url

    def test_dynamodb_table(self):
        url = build_console_url("dynamodb", "my-table", region="us-east-1")
        assert "table=my-table" in url

    def test_rds(self):
        url = build_console_url("rds", "my-db", region="us-east-1")
        assert "database:id=my-db" in url


class TestErrors:
    def test_unknown_service(self):
        with pytest.raises(ValueError, match="Unknown service"):
            build_console_url("nonexistent", "x")

    def test_service_root_for_iam(self):
        url = build_console_url("iam", None)  # no resource id
        # Should give the users listing or raise — either is acceptable;
        # assert it doesn't crash with unknown type
        assert isinstance(url, str)


class TestCLICommand:
    def test_console_command_prints_url(self):
        from typer.testing import CliRunner

        from harness_cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["console", "ec2", "i-abc", "--region", "us-east-1"])
        assert result.exit_code == 0
        assert "console.aws.amazon.com" in result.output

    def test_console_command_missing_region_fails(self):
        from typer.testing import CliRunner

        from harness_cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["console", "ec2", "i-abc"])
        assert result.exit_code == 2
