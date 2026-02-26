"""A limited interface to ServiceNow.

Provides a class, `ServiceNow`, which wraps the ServiceNow
API. The only functions are:

- To get a list of unassigned tickets;
- To get full details of a ticket;
- To assign oneself to a ticket; and
- To post a “work note” to a ticket.

Tickets are returned as instances of a `Ticket` dataclass which
contains a few, high-level details. The subclass `FullTicket` contains
in addition the fields submitted by the requestor on the request form.

The URL of the ServiceNow API is hardcoded, but you will need to
supply a user authentication token.

This version filters out all tickets that are not requests for HPC or
Azure resource.
"""

from dataclasses import dataclass
import requests


@dataclass
class Ticket:
    """A ticket; contains only high-level details about the ticket."""
<<<<<<< HEAD
    sys_id            : str
=======

    sys_id: str
>>>>>>> origin/issue-7-servicenow
    """The internal ServiceNow identifier for the ticket."""
    number            : str
    """The ticket number as recognised by agents."""
    opened_at         : str
    requested_for     : str
    u_category        : str
    u_sub_category    : str
    short_description : str


@dataclass
class FullTicket(Ticket):
    """Full details from the original submission."""
<<<<<<< HEAD
    work_notes                  : str
    project_title               : str
    research_area_programme     : str
    if_other_please_specify     : str
    pi_supervisor_name          : str
    pi_supervisor_email         : str
    which_service               : str
    subscription_type           : str
    which_finance_code          : str
    pmu_contact_email           : str
    credits_requested           : str
    which_facility              : str
=======

    work_notes: str
    project_title: str
    research_area_programme: str
    if_other_please_specify: str
    pi_supervisor_name: str
    pi_supervisor_email: str
    which_service: str
    subscription_type: str
    which_finance_code: str
    pmu_contact_email: str
    credits_requested: str
    which_facility: str
>>>>>>> origin/issue-7-servicenow
    if_other_please_specify_facility: str
    cpu_hours_required          : str
    gpu_hours_required          : str
    new_or_existing_allocation  : str
    azure_subscription_id_or_hpc_group_project_id: str
    start_date                  : str
    end_date                    : str
    data_sensitivity            : str
    platform_justification      : str
    research_justification      : str
    computational_requirements  : str
    users_who_require_access_names_and_emails: str
    cost_compute_time_breakdown : str


## TODO: Delete all of this
_TICKET_FIELDS = [
    "sys_id",
    "number",
    "opened_at",
    "requested_for",
    "u_category",
    "u_sub_category",
    "short_description",
]

# Maps FullTicket field names to ServiceNow API field names.
_VARIABLE_FIELD_MAP = {
    "work_notes": "work_notes",
    "project_title": "variables.project_title",
    "research_area_programme": "variables.research_area_programme",
    "if_other_please_specify": "variables.if_other_please_specify",
    "pi_supervisor_name": "variables.pi_supervisor_name",
    "pi_supervisor_email": "variables.pi_supervisor_email",
    "which_service": "variables.which_service",
    "subscription_type": "variables.subscription_type",
    "which_finance_code": "variables.which_finance_code",
    "pmu_contact_email": "variables.pmu_contact_email",
    "credits_requested": "variables.credits_requested",
    "which_facility": "variables.which_facility",
    "if_other_please_specify_facility": "variables.if_other_please_specify_facility",
    "cpu_hours_required": "variables.cpu_hours_required",
    "gpu_hours_required": "variables.gpu_hours_required",
    "new_or_existing_allocation": "variables.new_or_existing_allocation",
    "azure_subscription_id_or_hpc_group_project_id": "variables.azure_subscription_id_or_hpc_group_project_id",
    "start_date": "variables.start_date",
    "end_date": "variables.end_date",
    "data_sensitivity": "variables.data_sensitivity",
    "platform_justification": "variables.platform_justification",
    "research_justification": "variables.research_justification",
    "computational_requirements": "variables.computational_requirements",
    "users_who_require_access_names_and_emails": "variables.users_who_require_access_names_and_emails",
    "cost_compute_time_breakdown": "variables.cost_compute_time_breakdown",
}

# Reverse lookup: ServiceNow API field name -> FullTicket field name
_API_TO_FIELD = {v: k for k, v in VARIABLE_FIELD_MAP.items()}


def _extract_display_values(record: dict, fields: list[str]) -> dict:
    """Extract string values from a ServiceNow record.

    When sysparm_display_value=true, reference fields come back as
    {"display_value": "...", "link": "..."} dicts. This extracts
    the display_value string; non-dict values are passed through as-is.
    """
    result = {}
    for field in fields:
        val = record.get(field, "")
        if isinstance(val, dict):
            result[field] = val.get("display_value", "")
        else:
            result[field] = val
    return result


class ServiceNow:
    """Simple wrapper around limited parts of the ServiceNow API.

       Example:
       >>> the_service = ServiceNow("abc...efg")
    
    """

    # ServiceNow configuration 
    _BASE_URL = "https://turing-api.azure-api.net/dev-research/api/now/table"
    _TABLE    = "x_tati_resmgt_research"
    _FILTER   = "assigned_toISEMPTY^short_description=Request access to HPC and cloud computing facilities" 

    def __init__(self, token: str):
        self.endpoint = f"{self.BASE_URL}/{self.TABLE}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Ocp-Apim-Subscription-Key": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def get_unassigned_tickets(self) -> list[Ticket]:

        """Get unassigned tickets."""

        ## Get the list of unassigned tickets as JSON
        params = {
            "sysparm_query": _FILTER,
            "sysparm_display_value": "all",
        }
        resp = self.session.get(self.endpoint, params=params)
        resp.raise_for_status()
        return [
            Ticket(**_extract_display_values(record, TICKET_FIELDS))
            for record in resp.json()["result"]
        ]

    def get_full_ticket(self, ticket: Ticket) -> FullTicket:
        """Get full ticket details."""
        all_api_fields = TICKET_FIELDS + list(VARIABLE_FIELD_MAP.values())
        params = {
            "sysparm_fields": ",".join(all_api_fields),
            "sysparm_display_value": "true",
        }
        resp = self.session.get(f"{self.endpoint}/{ticket.sys_id}", params=params)
        resp.raise_for_status()
        record = resp.json()["result"]

        kwargs = _extract_display_values(record, TICKET_FIELDS)
        for field_name, api_name in VARIABLE_FIELD_MAP.items():
            kwargs[field_name] = record.get(api_name, "")

        return FullTicket(**kwargs)

    def post_note(self, ticket: Ticket, note: str) -> None:
        """Post a work note to a ticket."""
        resp = self.session.patch(
            f"{self.endpoint}/{ticket.sys_id}",
            json={"work_notes": note},
        )
        resp.raise_for_status()

    def assign_myself(self, ticket: Ticket) -> None:
        """Assign the current user to a ticket.

        Looks up the current user's sys_id via the sys_user table using
        the same bearer token, then patches the ticket's assigned_to field.
        Note: this assumes the /api/now/table/sys_user endpoint is accessible
        and that the token maps to a user with a 'user_name' field. This may
        need adjustment depending on the ServiceNow instance configuration.
        """
        user_sys_id = self._get_current_user_sys_id()
        resp = self.session.patch(
            f"{self.endpoint}/{ticket.sys_id}",
            json={"assigned_to": user_sys_id},
        )
        resp.raise_for_status()

    def _get_current_user_sys_id(self) -> str:
        """Get the sys_id of the currently authenticated user.

        Uses the sys_user table with sysparm_limit=1 and a query scoped to
        the authenticated session. This is a best-effort approach — the exact
        mechanism may vary by ServiceNow instance configuration.
        """
        user_url = f"{self.BASE_URL}/sys_user"
        params = {
            "sysparm_query": "user_name=javascript:gs.getUserName()",
            "sysparm_fields": "sys_id",
            "sysparm_limit": "1",
        }
        resp = self.session.get(user_url, params=params)
        resp.raise_for_status()
        results = resp.json()["result"]
        if not results:
            raise RuntimeError("Could not determine current user sys_id")
        return results[0]["sys_id"]
