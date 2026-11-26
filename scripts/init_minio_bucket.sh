#!/bin/sh
set -eu
# mc can include identities and generated credentials in success and error output.
exec 3>&2 >/dev/null 2>&1
stage=校验部署参数
trap 'if [ "$?" -ne 0 ]; then echo "MinIO 初始化失败（$stage）。" >&3; fi' EXIT
umask 077
export MC_CONFIG_DIR=/tmp/mc
case "${APP_ENV:-local}" in
  local|test|testing|development) ;;
  *)
    if [ -z "${MINIO_ROOT_USER:-}" ] || [ -z "${MINIO_ROOT_PASSWORD:-}" ] ||
       [ "${MINIO_ROOT_USER}" = "enterprise_agent" ] ||
       [ "${MINIO_ROOT_PASSWORD}" = "enterprise_agent_change_me" ] ||
       [ "${MINIO_ROOT_PASSWORD}" = "replace-with-a-strong-object-storage-secret" ]; then
      echo "unsafe MinIO credentials for non-local APP_ENV" >&2
      exit 1
    fi
    ;;
esac
file_id=$(cat /run/secrets/file_storage_bootstrap_access_key)
case "$FILE_STORAGE_BUCKET" in
  ''|browser-evidence|*[!a-z0-9.-]*) exit 1 ;;
esac
case "$1" in
  files)
    bucket=$FILE_STORAGE_BUCKET
    access=$file_id
    secret=$(cat /run/secrets/file_storage_bootstrap_secret_key)
    ;;
  evidence)
    [ "${FILE_STORAGE_ENDPOINT_URL:?}" = "http://minio:9000" ] || exit 1
    bucket=browser-evidence
    access=${AWS_ACCESS_KEY_ID:?}
    secret=${AWS_SECRET_ACCESS_KEY:?}
    [ "$access" != "$file_id" ] && [ "$file_id" != "$MINIO_ROOT_USER" ] || exit 1
    ;;
  *) exit 1 ;;
esac
[ "${#access}" -ge 3 ] && [ "${#access}" -le 20 ] && [ "$access" != "$MINIO_ROOT_USER" ] || exit 1
[ "${#secret}" -ge 8 ] && [ "${#secret}" -le 40 ] && [ "$secret" != "$MINIO_ROOT_PASSWORD" ] || exit 1
stage=连接对象存储
mc alias set admin http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
stage=创建私有桶
mc mb --ignore-existing "admin/$bucket"
stage=关闭匿名访问
mc anonymous set none "admin/$bucket"

cat > /tmp/bucket-policy.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:ListBucket","s3:GetBucketLocation","s3:ListBucketMultipartUploads"],"Resource":["arn:aws:s3:::$bucket"]},
  {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:AbortMultipartUpload","s3:ListMultipartUploadParts"],"Resource":["arn:aws:s3:::$bucket/*"]}
]}
EOF
managed_name="enterprise-agent-$1"
if mc admin accesskey info --json admin "$access" > /tmp/identity.json; then
  stage=核对既有身份用途
  case "$(tr -d '[:space:]' < /tmp/identity.json)" in
    *'"name":"'"$managed_name"'"'*) ;;
    *) exit 1 ;;
  esac
  # Authenticate the existing key before reconciling its policy. Never rotate on retry.
  stage=验证既有身份
  mc alias set scoped http://minio:9000 "$access" "$secret"
  stage=核对身份归属
  mc stat "scoped/$bucket"
  stage=更新桶权限
  mc admin accesskey edit admin "$access" --policy /tmp/bucket-policy.json
else
  stage=创建受限身份
  mc admin accesskey create admin/ --name "$managed_name" --access-key "$access" --secret-key "$secret" --policy /tmp/bucket-policy.json
fi
if [ "$1" = evidence ]; then
  stage=配置证据桶配额
  mc quota set "admin/$bucket" --size "${EVIDENCE_QUOTA:?}"
else
  stage=登记文件桶身份
  digest=/run/file-storage-identity/access.sha256
  printf %s "$access" | sha256sum | cut -d' ' -f1 > "$digest.tmp"
  chmod 0444 "$digest.tmp"
  mv -f "$digest.tmp" "$digest"
fi
