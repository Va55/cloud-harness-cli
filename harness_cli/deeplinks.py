"""
Console deep-link URL builder.

Maps (service, resource_id, region) → the direct console URL for that
resource — the bridge for console-native users: navigate by command,
jump straight to the one screen worth seeing.
"""

from typing import Optional

# Service → URL templates. {region}, {id} interpolated.
# Each entry: (template, requires_region, requires_id)
TEMPLATES = {
    "ec2": {
        "instance": "https://{region}.console.aws.amazon.com/ec2/home?region={region}#InstanceDetails:instanceId={id}",
        "volume": "https://{region}.console.aws.amazon.com/ec2/home?region={region}#VolumesDetails:volumeId={id}",
        "security-group": "https://{region}.console.aws.amazon.com/ec2/v2/home?region={region}#SecurityGroups:group-id={id}",
        "amis": "https://{region}.console.aws.amazon.com/ec2/home?region={region}#AMIs:",
    },
    "s3": {
        "bucket": "https://s3.console.aws.amazon.com/s3/buckets/{id}",
        "bucket-properties": "https://s3.console.aws.amazon.com/s3/buckets/{id}?region={region}&tab=properties",
    },
    "iam": {
        "user": "https://console.aws.amazon.com/iam/home#/users/{id}",
        "role": "https://console.aws.amazon.com/iam/home#/roles/{id}",
        "policy": "https://console.aws.amazon.com/iam/home#/policies/{id}",
        "users": "https://console.aws.amazon.com/iam/home#/users",
        "roles": "https://console.aws.amazon.com/iam/home#/roles",
    },
    "cloudfront": {
        "distribution": "https://console.aws.amazon.com/cloudfront/v4/home#/distributions/{id}",
        "distributions": "https://console.aws.amazon.com/cloudfront/v4/home#/distributions",
    },
    "lambda": {
        "function": "https://{region}.console.aws.amazon.com/lambda/home?region={region}#/functions/{id}",
        "functions": "https://{region}.console.aws.amazon.com/lambda/home?region={region}#/functions",
    },
    "vpc": {
        "vpc": "https://{region}.console.aws.amazon.com/vpc/home?region={region}#VpcDetails:VpcId={id}",
        "vpcs": "https://{region}.console.aws.amazon.com/vpc/home?region={region}#vpcs:",
    },
    "rds": {
        "database": "https://{region}.console.aws.amazon.com/rds/home?region={region}#database:id={id};is-cluster=false",
    },
    "dynamodb": {
        "table": "https://{region}.console.aws.amazon.com/dynamodb/home?region={region}#tables?table={id}",
    },
    "route53": {
        "hosted-zone": "https://console.aws.amazon.com/route53/v2/hostedzones",
    },
}


def _guess_resource_type(service: str, resource_id: Optional[str]) -> str:
    """Infer the resource type from the ID shape."""
    if not resource_id:
        return ""  # listing page (service root)
    rid = resource_id.lower()
    if service == "ec2":
        if rid.startswith("i-"):
            return "instance"
        if rid.startswith("vol-"):
            return "volume"
        if rid.startswith("sg-"):
            return "security-group"
        if rid.startswith("ami-"):
            return "amis"
    if service == "s3":
        return "bucket"
    if service == "iam":
        # Can't tell user vs role from a name — default to user
        return "user"
    if service == "cloudfront":
        return "distribution"
    if service == "lambda":
        return "function"
    if service == "vpc":
        if rid.startswith("vpc-"):
            return "vpc"
    if service == "rds":
        return "database"
    if service == "dynamodb":
        return "table"
    return ""


def build_console_url(service: str, resource_id: Optional[str],
                      region: Optional[str] = None) -> str:
    """Build the direct console URL for a resource.

    service: ec2|s3|iam|cloudfront|lambda|vpc|rds|dynamodb|route53
    resource_id: the resource identifier (i-..., vol-..., bucket name...)
    region: required for regional resources (ec2, lambda, vpc, ...)

    Raises ValueError for unknown services/shape mismatches.
    """
    service = service.lower()
    if service not in TEMPLATES:
        raise ValueError(
            f"Unknown service '{service}'. Supported: {', '.join(sorted(TEMPLATES))}"
        )

    res_type = _guess_resource_type(service, resource_id)

    # Listing page (no resource id)
    if not resource_id:
        # Use the first template that doesn't need {id}, or synthesize
        for template in TEMPLATES[service].values():
            if "{id}" not in template:
                if "{region}" in template and not region:
                    raise ValueError(
                        f"{service} listing page needs --region"
                    )
                return template.format(region=region or "", id="")
        raise ValueError(f"{service} needs a resource ID")

    if res_type not in TEMPLATES[service]:
        raise ValueError(
            f"Cannot determine resource type for {service} id '{resource_id}'"
        )

    template = TEMPLATES[service][res_type]
    if "{region}" in template and not region:
        raise ValueError(
            f"{service}:{res_type} is regional — pass --region"
        )
    return template.format(region=region or "", id=resource_id)
