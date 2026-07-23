# Security policy

Do not open public issues containing credentials, private agent data, or exploit
details. Report suspected credential exposure or an agent-safety vulnerability to the
maintainer through GitHub's private vulnerability reporting for this repository.

Supported releases are the latest minor release. Rotate any credential that may have
entered a commit, build log, shell history, artifact, or agent transcript; deleting the
current file is not sufficient because Git history and caches may retain it.

This is a single-owner application with tools capable of external side effects. Keep
authentication enabled, use TLS outside localhost, review pending approvals, mount
only intended data, and run one replica.

## Runtime-configured secrets

Secrets entered through the setup wizard or Settings UI (gateway API key,
SMTP password, password hash, auto-generated session secret) are stored
unencrypted in the application database and are never returned by the API.
The database inherits the trust level of the `/data` volume — restrict
access to it. The one-time setup token appears in service logs until the
instance is claimed; if it leaks pre-claim, delete the
`app-settings/setup-token` document (or restart with a fresh
`SWITCHGEAR_SETUP_TOKEN`) to rotate it.
