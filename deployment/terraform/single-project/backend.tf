terraform {
  backend "gcs" {
    bucket = "gen-lang-client-0675989879-terraform-state"
    prefix = "ambient-expense-agent/dev"
  }
}
