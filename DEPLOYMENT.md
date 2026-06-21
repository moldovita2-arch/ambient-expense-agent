# Google Cloud Deployment Guide (Backend)

This guide details exactly how the ADK (Agent Development Kit) backend is deployed securely to Google Cloud Run.

## 🏗 Architecture Overview
The deployment consists of two primary services in Google Cloud:
1. **Frontend (`ambient-expense-agent-frontend`)**: A publicly accessible Cloud Run service that acts as a secure reverse proxy.
2. **Backend (`ambient-expense-agent`)**: This repository. It is a highly-secure, private Cloud Run service running the ADK Python agent. **It is not publicly accessible on the internet.**

## 📦 Containerization (`Dockerfile`)
The backend is packaged into a Docker container.
- It uses a lightweight Python base image.
- Dependencies are managed using `uv` (or `pip`).
- The entrypoint spins up the ADK server (typically using `uvicorn` and FastAPI) on port `8080`.

## 🚀 CI/CD Pipeline (Cloud Build)
We use Google Cloud Build to automate deployments. When changes are pushed to this repository:
1. **Docker Build**: A new container image is built containing the updated agent logic.
2. **Docker Push**: The image is pushed to Google Container Registry (GCR) or Artifact Registry.
3. **Cloud Run Deploy**: The new image is deployed to the `ambient-expense-agent` Cloud Run service.

### Cloud Build Service Account
The Cloud Build pipeline runs under a dedicated service account (e.g., `ambient-expense-agent-cb@<project-id>.iam.gserviceaccount.com`).
For this pipeline to successfully deploy the backend, this builder account is granted:
- `roles/run.admin`: To create and update Cloud Run services.
- `roles/iam.serviceAccountUser` (`iam.serviceAccounts.actAs`): To attach the runtime service account to the deployed Cloud Run instance.

## 🔐 IAM and Security Configuration

Security is paramount for this backend. It is configured as a private, Zero-Trust service.

### 1. Private Ingress (No Public Access)
Unlike the frontend, this backend service is deployed with **Require Authentication**. 
- It does **not** allow unauthenticated access.
- Any request made to this service without a valid, cryptographically signed Google Cloud Identity Token is immediately rejected by the Google Front End (GFE) with an HTTP `403 Forbidden` error.

### 2. Runtime Service Account
The backend runs under its own dedicated service account (e.g., `ambient-expense-agent-app@<project-id>.iam.gserviceaccount.com`).
- This follows the principle of least privilege.
- If the agent needs to access a database, call a Vertex AI model, or publish to Pub/Sub, those permissions are granted explicitly to this `app` service account.

### 3. Service-to-Service Invocation
Because the backend is private, the frontend needs explicit permission to call it.
- The frontend runs under its own service account (or the default Compute Engine service account).
- We grant the frontend's service account the **`roles/run.invoker`** role exactly on this `ambient-expense-agent` Cloud Run service.
- The frontend then fetches an Identity Token specifically for this backend's URL and attaches it as a `Bearer` token in the `Authorization` header.

## 🛠 Manual Deployment
If you need to deploy the backend manually using the `gcloud` CLI (bypassing Cloud Build), use the following command:

```bash
gcloud run deploy ambient-expense-agent \
  --source . \
  --region europe-west2 \
  --no-allow-unauthenticated \
  --service-account="ambient-expense-agent-app@<your-project-id>.iam.gserviceaccount.com"
```
