# MinIO Configuration
MinIO is used as target for velero backups. This describes how to create a
dedicated bucket with its associated user.

Install the [MinIO Client][1]. On Arch (as `mcli` instead of `mc`):
```bash
sudo pacman -S minio-client
```

The MinIO client can connect to different servers. Add an alias and
configuration for yours with:
```bash
mcli alias set minio http://minio:9000
```

Create a dedicated user for velero:
```bash
mcli admin user add minio velero
```

Create a bucket:
```bash
mcli mb minio/velero
```

Create a policy for that bucket:
```bash
cat > /tmp/velero-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:PutObject",
                "s3:AbortMultipartUpload",
                "s3:ListMultipartUploadParts"
            ],
            "Resource": [
                "arn:aws:s3:::velero/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::velero"
            ]
        }
    ]
}
EOF

mcli admin policy add minio velero /tmp/velero-policy.json
```

Set policy for user:
```bash
mcli admin policy set minio velero user=velero
```

All set!

[1]: https://docs.min.io/docs/minio-client-quickstart-guide.html
