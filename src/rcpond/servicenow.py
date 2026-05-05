"""A limited interface to ServiceNow.

Provides a class, `ServiceNow`, which wraps the ServiceNow
API. The only methods are:

- `ServiceNow.get_tickets()`: Get a list of tickets. By default only unassigned tickets are returned, but all tickets can be selected;
- `ServiceNow.get_ticket()`: Get a single ticket by its ticket number (e.g. ``"RES0001234"``);
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
>>> the_sn.get_tickets()

"""

from __future__ import annotations

import base64
import dataclasses
import json
from dataclasses import dataclass

import requests

from rcpond import __version__ as rcpond_version
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
    state: str
    """Human-readable ticket state, e.g. 'New', 'In Progress', 'On Hold', 'Resolved', 'Closed'."""
    assigned_to: str
    """Display name of the assigned agent, or empty string if unassigned."""

    def assign_to_me(self, service_now: ServiceNow) -> None:
        """Assign this ticket to the currently authenticated OAuth user.

        Parameters
        ----------
        service_now : ServiceNow
            The ServiceNow client. Must be configured with OAuth credentials.

        Raises
        ------
        NotImplementedError
            If the ServiceNow client is using static token authentication.
        """
        service_now.assign_to_me(self)


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
        self._web_base_url: str = config.servicenow_web_url
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        if config.servicenow_client_id and config.servicenow_client_secret:
            from rcpond.auth import get_bearer_token

            self.session.headers["Authorization"] = f"Bearer {get_bearer_token(config)}"
            self._is_oauth = True
        else:
            self.session.headers["Ocp-Apim-Subscription-Key"] = config.servicenow_token or ""
            self._is_oauth = False

    def get_tickets(self, include_assigned_tickets: bool = False) -> list[Ticket]:
        """Get tickets that are applications for HPC/Azure
        credits.
        """

        _UNASSIGNED_FILTER = "assigned_toISEMPTY^short_description=Request access to HPC and cloud computing facilities"
        _INC_ASSIGNED_FILTER = "short_description=Request access to HPC and cloud computing facilities"

        query = _INC_ASSIGNED_FILTER if include_assigned_tickets else _UNASSIGNED_FILTER

        ticket_fields = {field.name for field in dataclasses.fields(Ticket)}

        ## Get the list of unassigned tickets as JSON
        resp = self.session.get(
            f"{self._base_url}/{self._TABLE}", params={"sysparm_query": query, "sysparm_display_value": "all"}
        )

        resp.raise_for_status()

        ## Parse the JSON for each ticket
        return [Ticket(**_extract_ticket_fields(tkt, ticket_fields)) for tkt in resp.json()["result"]]

    def get_ticket(self, ticket_number: str) -> Ticket:
        """Returns the unique ticket matching ``ticket_number``, or raise ValueError if either no match,
        or multiple matches are found.

        The specified ticket may be assigned or unassigned

        Parameters
        ----------
        ticket_number : str
            The ticket number to look up (e.g. ``"RES0001234"``).

        Raises
        ------
        ValueError
            If no ticket matches, or if more than one matches (should not happen
            in practice — ServiceNow enforces uniqueness, but guarded defensively).
        """
        matched = [t for t in self.get_tickets(include_assigned_tickets=True) if t.number == ticket_number]
        if len(matched) == 0:
            err_msg = f"Ticket '{ticket_number}' not found."
            raise ValueError(err_msg)
        if len(matched) > 1:
            ## ServiceNow should prevent duplicate ticket numbers, but guard defensively.
            detail = "\n\n".join(str(t) for t in matched)
            err_msg = f"Multiple tickets match '{ticket_number}':\n{detail}"
            raise ValueError(err_msg)
        return matched[0]

    def web_url(self, tkt: Ticket) -> str:
        """Return the ServiceNow Web UI URL for ``tkt``.

        Parameters
        ----------
        tkt : Ticket
            The ticket to generate a URL for.
        """
        return f"{self._web_base_url.rstrip('/')}/{self._TABLE}.do?sys_id={tkt.sys_id}"

    def get_full_ticket(self, tkt: Ticket) -> FullTicket:
        """Get full ticket details."""

        ## Get details from ServiceNow as JSON
        extra_fields = {field.name for field in dataclasses.fields(FullTicket)} - {
            field.name for field in dataclasses.fields(Ticket)
        }

        ## Variable fields (everything except work_notes) must be requested with the
        ## "variables." prefix — they are stored as ServiceNow catalogue variables,
        ## not top-level record fields.
        _TOPLEVEL = {"work_notes"}
        requested_fields = {f if f in _TOPLEVEL else f"variables.{f}" for f in extra_fields}

        resp = self.session.get(
            f"{self._base_url}/{self._TABLE}/{tkt.sys_id}",
            params={"sysparm_fields": ",".join(requested_fields), "sysparm_display_value": "all"},
        )

        resp.raise_for_status()

        ## Parse the returned JSON, stripping the "variables." prefix so the keys
        ## match FullTicket field names.
        result = {
            (k[len("variables.") :] if k.startswith("variables.") else k): v for k, v in resp.json()["result"].items()
        }

        return FullTicket.from_Ticket(tkt, **_extract_ticket_fields(result, extra_fields))

    def get_work_notes(self, tkt: Ticket) -> list[str]:
        resp = self.session.get(
            f"{self._base_url}/{self._TABLE}/{tkt.sys_id}",
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
            f"{self._base_url}/{self._TABLE}/{tkt.sys_id}",
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
        prefix: str = f"[code]<b>RCPond v{rcpond_version} generated response:</b>[/code]\n" "----\n"

        ## This will append the `note` param to `work_notes` field
        resp = self.session.patch(
            f"{self._base_url}/{self._TABLE}/{tkt.sys_id}",
            json={"work_notes": prefix + note},
        )
        resp.raise_for_status()

    def _current_user_sys_id(self) -> str:
        """Decode the JWT bearer token and return the current user's sys_id.

        The ServiceNow OAuth JWT carries the user's sys_id in the ``sub`` claim.
        """
        auth = self.session.headers["Authorization"]
        token = (auth.decode() if isinstance(auth, bytes) else auth).removeprefix("Bearer ")
        payload_b64 = token.split(".")[1]
        ## base64url requires padding to a multiple of 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        return payload["sub"]

    def assign_to_me(self, ticket: Ticket) -> dict[str, str]:
        """Assign ``ticket`` to the currently authenticated OAuth user.

        Parameters
        ----------
        ticket : Ticket
            The ticket to assign.

        Returns
        -------
        dict[str, str]
            The updated assignee dict (``display_value`` and ``value``).

        Raises
        ------
        NotImplementedError
            If the client is using static token authentication, which does not
            carry a per-user identity. OAuth credentials (``servicenow_client_id``
            + ``servicenow_client_secret``) are required to use this feature.
        """
        if not self._is_oauth:
            msg = (
                "assign_to_me() requires OAuth authentication.\n"
                "Static token auth does not carry a per-user identity.\n"
                "Set servicenow_client_id and servicenow_client_secret in your config to enable this feature."
            )
            raise NotImplementedError(msg)
        return self.assign_to(ticket, self._current_user_sys_id())

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
            assignee: The email address or sys_id (as a str) of the user to assign the ticket to.

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
            if new_assignee["display_value"] != "" or new_assignee["value"] != "":
                err_msg = f"Expected ticket '{ticket.number}' to be unassigned but got: {new_assignee}"
                raise RuntimeError(err_msg)
            ticket.assigned_to = ""
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

        ticket.assigned_to = new_assignee["display_value"]
        return new_assignee
