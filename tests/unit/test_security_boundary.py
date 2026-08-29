import pytest
from agentops.clients.kubernetes import KubernetesInvestigationClient


def test_no_mutation_methods_in_kubernetes_client():
    """
    Security Guarantee Test:
    Ensures that the Kubernetes client has ZERO mutation/write capabilities.
    """
    client = KubernetesInvestigationClient()
    prohibited_keywords = [
        "delete",
        "patch",
        "update",
        "scale",
        "restart",
        "exec",
        "create",
        "apply",
        "post",
        "put",
    ]

    all_methods = [
        method for method in dir(client)
        if callable(getattr(client, method)) and not method.startswith("__")
    ]

    for method_name in all_methods:
        lower_name = method_name.lower()
        for prohibited in prohibited_keywords:
            assert prohibited not in lower_name, (
                f"Security Violation: Found prohibited mutation method '{method_name}' in read-only Kubernetes client!"
            )


def test_command_filter_blocks_unauthorized_kubectl():
    """
    Security Guard Test:
    Ensures that any attempt to execute non-read-only kubectl commands is rejected.
    """
    client = KubernetesInvestigationClient()

    unauthorized_commands = [
        ["kubectl", "delete", "pod", "demo-app-123"],
        ["kubectl", "scale", "deployment", "demo-app", "--replicas=0"],
        ["kubectl", "exec", "-it", "demo-app-123", "--", "rm", "-rf", "/"],
        ["kubectl", "patch", "deployment", "demo-app", "-p", "{}"],
        ["rm", "-rf", "/tmp"],
        ["bash", "-c", "echo hack"],
    ]

    for cmd in unauthorized_commands:
        with pytest.raises(PermissionError):
            client._run_read_only_cmd(cmd)
