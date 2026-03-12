"""A limited interface to ServiceNow.

Provides a class, `ServiceNow`, which wraps the ServiceNow
API. The only methods are:

- `ServiceNow.get_unassigned_tickets()`: Get a list of unassigned tickets;
- `ServiceNow.get_full_ticket()`: Get full details of a ticket;
- `assign_to()` Assigns a ticket to the named user;
- `get_work_notes()` List the work notes for a specific ticket; and
- `post_note()` (Not implemented) Post a “work note” to a ticket.

Tickets are returned as instances of a `Ticket` dataclass which
contains a few, high-level details. The subclass `FullTicket` contains
,in addition, the fields submitted by the requestor on the request form.

The URL of the ServiceNow API is hardcoded, but you will need to
supply a user authentication token.

This version filters out all tickets that are not requests for HPC or
Azure resource.

Example use
-----------

>>> the_sn = ServiceNow("ab...def")
>>> the_sn.get_unassigned_tickets()

"""

import dataclasses
from dataclasses import dataclass

import requests

from rcpond.config import Config


@dataclass
class Ticket:
    """A ticket; contains only high-level details about the ticket."""

    sys_id: str
    """The internal ServiceNow identifier for the ticket."""
    number: str
    """The ticket number as recognised by agents."""
    opened_at: str
    """A timestamp, formatted as `DD/MM/YYYY HH:MM:SS` """
    requested_for: str
    u_category: str
    u_sub_category: str
    short_description: str


@dataclass
class FullTicket(Ticket):
    """A ticket; includes full details from the original submission."""

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
    if_other_please_specify_facility: str
    cpu_hours_required: str
    gpu_hours_required: str
    new_or_existing_allocation: str
    azure_subscription_id_or_hpc_group_project_id: str
    start_date: str
    end_date: str
    data_sensitivity: str
    platform_justification: str
    research_justification: str
    computational_requirements: str
    users_who_require_access_names_and_emails: str
    cost_compute_time_breakdown: str

    @classmethod
    def from_Ticket(cls, t: Ticket, **extras):
        """Create a new FullTicket starting from a Ticket and passing
        only the additional fields.
        """
        return cls(**(dataclasses.asdict(t)), **extras)


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


## tkt: The JSON from the API call (as a dictionary)
def _extract_ticket_fields(tkt: dict[str, dict | str], fields: set[str]) -> dict:
    return {field: _extract_display_value(tkt.get(field, "")) for field in fields}


def _parse_comment_display_values(input: str) -> list[str]:
    split_str = input.split("\n\n")
    ## filter out empty strings
    return [s for s in split_str if s]


## --------------------------------------------------------------------------------
## Interface to this module


class ServiceNow:
    """Simple wrapper around limited parts of the ServiceNow API."""

    # ServiceNow configuration
    # _base_url = "https://turing-api.azure-api.net/dev-research/api/now/table"
    _TABLE = "x_tati_resmgt_research"

    def __init__(self, config: Config):
        self._base_url = config.servicenow_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Ocp-Apim-Subscription-Key": config.servicenow_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def get_tickets(self, include_assigned_tickets: bool = False) -> list[Ticket]:
        """Get tickets that are applications for HPC/Azure
        credits.
        """

        _UNASSIGNED_FILTER = "assigned_toISEMPTY^short_description=Request access to HPC and cloud computing facilities"
        _INC_ASSIGNED_FILTER = "short_description=Request access to HPC and cloud computing facilities"

        filter = _INC_ASSIGNED_FILTER if include_assigned_tickets else _UNASSIGNED_FILTER

        ticket_fields = {field.name for field in dataclasses.fields(Ticket)}

        ## Get the list of unassigned tickets as JSON
        resp = self.session.get(
            self._base_url + "/" + self._TABLE, params={"sysparm_query": filter, "sysparm_display_value": "all"}
        )

        resp.raise_for_status()

        ## Parse the JSON for each ticket
        return [Ticket(**_extract_ticket_fields(tkt, ticket_fields)) for tkt in resp.json()["result"]]

    def get_full_ticket(self, tkt: Ticket) -> FullTicket:
        """Get full ticket details."""

        ## Get details from ServiceNow as JSON
        extra_fields = {field.name for field in dataclasses.fields(FullTicket)} - {
            field.name for field in dataclasses.fields(Ticket)
        }

        resp = self.session.get(
            self._base_url + "/" + self._TABLE + "/" + tkt.sys_id,
            params={"sysparm_fields": ",".join(extra_fields), "sysparm_display_value": "all"},
        )

        resp.raise_for_status()

        ## Parse the returned JSON
        result = resp.json()["result"]

        return FullTicket.from_Ticket(tkt, **_extract_ticket_fields(result, extra_fields))

    def get_work_notes(self, tkt: Ticket) -> list[str]:
        print(tkt.sys_id)

        resp = self.session.get(
            self._base_url + "/" + self._TABLE + "/" + tkt.sys_id,
            params={
                "sysparm_display_value": "true",
                "sysparm_exclude_reference_link": "true",
                "sysparm_fields": "work_notes",
                "sysparm_query_no_domain": "false",
            },
        )
        resp.raise_for_status()

        raw_result = resp.json()["result"]["work_notes"]
        return _parse_comment_display_values(raw_result)

    def get_assignee(self, tkt: Ticket) -> dict[str, str]:
        """
        A convenience method to retrieve the current `assigned_to` field for a Ticket.

        returns:
            A dict with two keys `display_value` and `value`
        """
        resp = self.session.get(
            self._base_url + "/" + self._TABLE + "/" + tkt.sys_id,
            params={
                "sysparm_display_value": "all",
                "sysparm_exclude_reference_link": "true",
                "sysparm_fields": "assigned_to",
                "sysparm_query_no_domain": "false",
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["assigned_to"]

    def post_note(self, tkt: Ticket, note: str) -> None:
        """Post a work note to a ticket.

        Params:
            tkt: The ticket
            note: The note to post
        """
        ## This will append the `note` param to `work_notes` field
        resp = self.session.patch(
            self._base_url + "/" + self._TABLE + "/" + tkt.sys_id,
            json={"work_notes": note},
        )
        resp.raise_for_status()

    def _attempt_assign_to(self, ticket: Ticket, assignee: str) -> None:
        resp = self.session.patch(
            f"{self._base_url}/{self._TABLE}/{ticket.sys_id}",
            json={"assigned_to": assignee},
        )
        resp.raise_for_status()

    def assign_to(self, ticket: Ticket, assignee: str) -> dict[str, str]:
        """Assign the current user to a ticket.

        **Post-hoc validation is performed that this assignee exists in the ServiceNow instance. If an invalid value for `assignee` is provided. The method will assign the ticket to the invalid user, detect that it is invalid, and then revert the assignment to the original assignee. This interaction will show in the Activity log for the ticket in the ServiceNow WebUI**

        Example:
        >>> sn.assign_to(my_tkt, "sam@example.com")

        To unassign a ticket, set assignee == "":
        >>> sn.assign_to(my_tkt, "")

        Params:
            ticket: The ticket to be assigned
            assignee: The email address (as a str) of the user to assign the ticket to.

        Returns:
            A dict with two keys `display_value` and `value`
        """
        _original_assignee = self.get_assignee(ticket)

        # Attempt assignment
        self._attempt_assign_to(ticket, assignee)

        # Verify success
        new_assignee = self.get_assignee(ticket)

        # The required result is to unassign the ticket (eg assignee is "" or None)
        if not assignee:
            assert new_assignee["display_value"] == ""
            assert new_assignee["value"] == ""
            return new_assignee

        ## If the assign_to value was not recognised by ServiceNow, then the
        ## display_value will be empty
        if not new_assignee["display_value"]:
            # Reset the assignee to the original value
            # Trust that this works correctly
            self._attempt_assign_to(ticket, _original_assignee["value"])
            err_msg = (
                f"Unable to assign ticket '{ticket.number}' to the user '{assignee}'"
                " The user was not recognised by ServiceNow."
                f" The ticket has been re-assigned back to the original assignee '{_original_assignee['display_value']}/{_original_assignee['value']}'"
            )
            raise ValueError(err_msg)

        return new_assignee


## --------------------------------------------------------------------------------
## Non-functioning exploration of how to identify the user making the calls

# def get_current_user_sys_id(self) -> str:
#     """Get the sys_id of the currently authenticated user.

#     Uses the sys_user table with sysparm_limit=1 and a query scoped to
#     the authenticated session. This is a best-effort approach — the exact
#     mechanism may vary by ServiceNow instance configuration.
#     """

#     user_url = "https://turing-api.azure-api.net/dev-research/api/now/account"
#     # user_url = f"{self._base_url}/sys_user"
#     params = {
#         # "sysparm_query": "user_name=javascript:gs.getUserName()",
#         "sysparm_query": "caller_id=javascript:gs.getUserID()^active=true",
#         "sysparm_fields": "sys_id",
#         "sysparm_limit": "1",
#     }
#     resp = self.session.get(user_url, params=params)
#     resp.raise_for_status()
#     results = resp.json()["result"]
#     if not results:
#         err_msg = "Could not determine current user sys_id"
#         raise RuntimeError(err_msg)
#     return results[0]["sys_id"]

# def get_user_end_point(self) -> dict:
#     """Probe the sys_user table for current-user information.

#     Queries ``{_base_url}/sys_user`` (the standard ServiceNow Table API
#     path).  Returns the parsed JSON response body.
#     Raises ``requests.HTTPError`` on a non-2xx response (e.g. 404 if the
#     sys_user table is not exposed through the API gateway).
#     """
#     resp = self.session.get(
#         f"{self._base_url}/sys_user",
#         params={
#             "sysparm_fields": "sys_id,name,user_name,email",
#             "sysparm_limit": "1",
#         },
#     )
#     resp.raise_for_status()
#     return resp.json()
