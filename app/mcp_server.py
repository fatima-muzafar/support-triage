from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Support Triage Server")

@mcp.tool()
def search_knowledge_base(query: str) -> str:
    """Search the support knowledge base for articles and documentation.

    Args:
        query: The search query (e.g., 'billing policy', 'password reset').

    Returns:
        Relevant knowledge base articles or troubleshooting guides.
    """
    query_lower = query.lower()
    if "billing" in query_lower or "invoice" in query_lower or "charge" in query_lower:
        return (
            "Invoice Policy: Customers can download invoice copies up to 12 months in the Billing portal. "
            "Refund requests must be escalated to the Billing Team and processed within 30 days of the transaction date."
        )
    elif "login" in query_lower or "password" in query_lower or "auth" in query_lower:
        return (
            "Account Reset Policy: For login issues, direct the customer to the /reset page. "
            "Never ask for password details in the support chat. Passwords must be 12+ characters."
        )
    elif "outage" in query_lower or "down" in query_lower or "incident" in query_lower:
        return (
            "Service Outage Protocol: If a service is down, check the status page. "
            "If it's a known issue, tell the customer: 'Our team is aware and working on it. Expected resolve time is 2 hours.'"
        )
    return (
        "Standard Troubleshooting: Clear browser cache and cookies, then try reloading the page. "
        "If the issue persists, escalate the ticket to Tier 2 Technical Support."
    )

@mcp.tool()
def get_customer_billing_info(customer_id: str) -> str:
    """Retrieve billing history and status for a given customer ID.

    Args:
        customer_id: The unique identifier of the customer (e.g., 'CUST-1001').

    Returns:
        Billing plan, status, and balance details.
    """
    # Simulated customer billing lookup
    return (
        f"Billing Info for {customer_id}:\n"
        f"- Plan: Enterprise Tier\n"
        f"- Status: Active\n"
        f"- Last Invoice: Paid on 2026-06-01\n"
        f"- Balance: $0.00\n"
        f"- Payment Method: Credit Card ending in 4321"
    )

@mcp.tool()
def get_system_status() -> str:
    """Check the current system status and active service incidents.

    Returns:
        A report on system uptime and any active outages.
    """
    return (
        "System Status Report:\n"
        "- Authentication Service: Operational (100% Uptime)\n"
        "- Database Cluster: Operational (99.98% Uptime)\n"
        "- Billing API: Operational (100% Uptime)\n"
        "- Web Dashboard: Operational (99.9% Uptime)\n"
        "Active Incidents: None"
    )

if __name__ == "__main__":
    mcp.run(transport="stdio")
