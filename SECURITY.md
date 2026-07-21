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
