# Turning on the nightly off-site backup

The app already knows how to upload a dated backup file every night at 02:00 EAT. It stays off until you give it a storage bucket. This takes about 10 minutes and needs only your own accounts: nobody else needs your keys.

## 1. Make a bucket (Cloudflare R2 shown; Backblaze B2 works the same way)
1. Sign in at cloudflare.com, open **R2 Object Storage**, and add a payment method if asked (the free allowance is far larger than these backups).
2. **Create bucket**, name it e.g. `khu-backups`.
3. Open the bucket → **Settings** and turn on a **bucket lock rule** (or object versioning if offered) so old backups cannot be overwritten or deleted by mistake.

## 2. Make an access key
1. R2 overview → **Manage API tokens** → **Create API token**.
2. Permission: **Object Read & Write**. Limit it to the `khu-backups` bucket only.
3. Copy the **Access Key ID**, the **Secret Access Key** and the bucket's **S3 endpoint** (looks like `https://<account>.r2.cloudflarestorage.com`). The secret is shown once.

## 3. Give them to Render
Render dashboard → the `khu-backend` service → **Environment** → add:

| Name | Value |
| --- | --- |
| `BACKUP_S3_ENDPOINT` | the S3 endpoint from step 2 |
| `BACKUP_S3_BUCKET` | `khu-backups` |
| `BACKUP_S3_KEY_ID` | the Access Key ID |
| `BACKUP_S3_SECRET` | the Secret Access Key |

Save. Render redeploys by itself.

## 4. Check it works
1. Open the admin page → **Data** tab → run the off-site backup now button.
2. You should see a success message, and a file named with today's date inside the bucket.
3. After the first night, a new file should appear around 02:00 EAT each day.

Never paste these keys into chat, GitHub or the frontend. If one leaks, delete the token in Cloudflare and make a new one.

## Restoring
Download any backup file from the bucket, then admin page → **Data** tab → restore. Restoring never overwrites rows that already exist.
