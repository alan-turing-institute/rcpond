"""A limited interface to ServiceNow.

Provides a class, `ServiceNow`, which wraps the ServiceNow
API. The only functions are:

- `get_unassigned_tickets`: To get a list of unassigned tickets;
- `get_full_ticket`: To get full details of a ticket;
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

import dataclasses
from dataclasses import dataclass
import requests


@dataclass
class Ticket:
    """A ticket; contains only high-level details about the ticket."""
    sys_id            : str
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
    """A ticket; includes full details from the original submission."""
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

    @classmethod
    def from_Ticket(cls, t: Ticket, **extras):
        """Create a new FullTicket starting from a Ticket and passing
        only the additional fields.
        """
        return cls(**dataclasses.asdict(t), **extras)


## --------------------------------------------------------------------------------
## Utilities
    
## Extract, from the record returned from ServiceNow, the fields
## defined in Ticket. A value in the record is either a string,
## or a dictionary with keys "value", "display_value", and (sometimes)
## "link". We usually want "display_value".
def _extract_display_value(fld: dict | str) -> str:
    if isinstance(fld, dict):
        return fld.get("display_value", "")
    else:
        return fld

def _extract_ticket_fields(tkt: dict) -> dict:
    return {
        field.name: _extract_display_value(tkt.get(field.name))
        for field in dataclasses.fields(Ticket)
    }



## --------------------------------------------------------------------------------
## The main class of this module
    
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
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Ocp-Apim-Subscription-Key": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )


    def get_unassigned_tickets(self) -> list[Ticket]:
        """Get unassigned tickets that are applications for HPC/Azure
           credits.
        """

        ## Get the list of unassigned tickets as JSON
        resp = self.session.get(self._BASE_URL + "/" + self._TABLE,
                                params = {
                                    "sysparm_query": self._FILTER,
                                    "sysparm_display_value": "all"
                                    }
                                )

        resp.raise_for_status()

        ## Parse the JSON for each ticket
        return [
            Ticket(** _extract_ticket_fields(tkt))
            for tkt in resp.json()["result"]
        ]


    def get_full_ticket(self, tkt: Ticket) -> FullTicket:
        """Get full ticket details."""

        ## Get details from ServiceNow as JSON
        extra_fields = [field.name for field in dataclasses.fields(FullTicket)]

        resp = self.session.get(self._BASE_URL + "/" + self._TABLE + "/" + tkt.sys_id,
                                params = {
                                    "sysparm_fields": ",".join(extra_fields),
                                    "sysparm_display_value": "true"
                                    }
                                )

        resp.raise_for_status()

        ## Parse the returned JSON
        record = resp.json()["result"]

        kwargs = _extract_display_values(record, TICKET_FIELDS)

        for field_name, api_name in VARIABLE_FIELD_MAP.items():
            kwargs[field_name] = record.get(api_name, "")

        return FullTicket.from_ticket(tkt, **extras)

    # def post_note(self, ticket: Ticket, note: str) -> None:
    #     """Post a work note to a ticket."""
    #     resp = self.session.patch(
    #         f"{self.endpoint}/{ticket.sys_id}",
    #         json={"work_notes": note},
    #     )
    #     resp.raise_for_status()

    # def assign_myself(self, ticket: Ticket) -> None:
    #     """Assign the current user to a ticket.

    #     Looks up the current user's sys_id via the sys_user table using
    #     the same bearer token, then patches the ticket's assigned_to field.
    #     Note: this assumes the /api/now/table/sys_user endpoint is accessible
    #     and that the token maps to a user with a 'user_name' field. This may
    #     need adjustment depending on the ServiceNow instance configuration.
    #     """
    #     user_sys_id = self._get_current_user_sys_id()
    #     resp = self.session.patch(
    #         f"{self.endpoint}/{ticket.sys_id}",
    #         json={"assigned_to": user_sys_id},
    #     )
    #     resp.raise_for_status()

    # def _get_current_user_sys_id(self) -> str:
    #     """Get the sys_id of the currently authenticated user.

    #     Uses the sys_user table with sysparm_limit=1 and a query scoped to
    #     the authenticated session. This is a best-effort approach — the exact
    #     mechanism may vary by ServiceNow instance configuration.
    #     """
    #     user_url = f"{self.BASE_URL}/sys_user"
    #     params = {
    #         "sysparm_query": "user_name=javascript:gs.getUserName()",
    #         "sysparm_fields": "sys_id",
    #         "sysparm_limit": "1",
    #     }
    #     resp = self.session.get(user_url, params=params)
    #     resp.raise_for_status()
    #     results = resp.json()["result"]
    #     if not results:
    #         raise RuntimeError("Could not determine current user sys_id")
    #     return results[0]["sys_id"]
