from collections.abc import Iterable

# Hand-maintained against the 14-service curated corpus; revisit when ingestion widens it.
SERVICE_ALIASES: dict[str, str] = {
    "aks": "Azure Kubernetes Service",
    "kubernetes": "Azure Kubernetes Service",
    "k8s": "Azure Kubernetes Service",
    "blob": "Azure Blob Storage (SFTP)",
    "blob storage": "Azure Blob Storage (SFTP)",
    "sftp": "Azure Blob Storage (SFTP)",
    "firewall": "Azure Firewall",
    "functions": "Azure Functions",
    "azure functions": "Azure Functions",
    "arm": "Azure Resource Manager",
    "resource manager": "Azure Resource Manager",
    "aca": "Azure Container Apps",
    "container apps": "Azure Container Apps",
    "acr": "Azure Container Registry",
    "container registry": "Azure Container Registry",
    "resource groups": "Azure Resource Groups",
    "azure resource groups": "Azure Resource Groups",
    "subscriptions": "Azure Subscriptions",
    "azure subscriptions": "Azure Subscriptions",
    "local": "Azure Local",
    "azure local": "Azure Local",
    "site recovery": "Azure Site Recovery (Scout 8.0.1)",
    "azure site recovery": "Azure Site Recovery (Scout 8.0.1)",
    "management groups": "Azure Management Groups",
    "azure management groups": "Azure Management Groups",
    "arm templates": "ARM Templates",
    "networking": "Azure Networking",
    "azure networking": "Azure Networking",
}

SUPPORT_STATUS_VERDICTS: dict[str, str] = {
    "supported": "supported",
    "not_supported": "unsupported",
    "retired": "unsupported",
    "known_issue": "constrained",
    "partially_supported": "constrained",
    "preview": "constrained",
    "deprecated": "constrained",
    "support_ticket_required": "constrained",
}


def resolve_query(raw: str) -> str | None:
    """Resolve a normalized query alias to its exact stored service name."""
    return SERVICE_ALIASES.get(raw.strip().lower())


def map_support_status(status: str) -> str:
    """Map a stored support status to the conservative public verdict vocabulary."""
    return SUPPORT_STATUS_VERDICTS.get(status, "constrained")


def aggregate_verdict(statuses: Iterable[str]) -> str:
    """Return the most severe verdict, defaulting empty input to supported."""
    verdicts = set(statuses)
    if "unsupported" in verdicts:
        return "unsupported"
    if "constrained" in verdicts:
        return "constrained"
    return "supported"
