/**
 * Frontend configuration. Set API_BASE_URL to the address of the backend:
 *  - local development:  http://localhost:8000
 *  - production:         the Azure Container App (see below)
 *
 * The end-to-end tests replace this file with a local configuration (see e2e/conftest.py),
 * so the value below is what the deployed website uses.
 */
window.APP_CONFIG = {
  API_BASE_URL: "https://unit-commitment-solver.ambitioussky-0b22f21d.germanywestcentral.azurecontainerapps.io",
};
