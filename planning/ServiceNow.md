% Interface to ServiceNow

This module exports a class, `SN` and dataclasses `ticket` and
`full_ticket` (a subclass of `ticket`). 

```python
class SN: 
    <...>
```

## Use

Use it as follows:

### Initialisation
```python
the_sn = SN(user_token)
```
where `token` is a string containing the user's authentication token.

### Getting tickets

Get the unassigned tickets related to "Request access to HPC and
cloud computing facilities".
```python
the_sn.get_unassigned_tickets()
```
Returns a list of `Ticket`s.

Get the full ticket information for a given ticket
```python
the_sn.get_full_ticket(ticket)
```
where ticket is a `Ticket`. Returns a `FullTicket`.

### Posting a work note

Post a work note:
```python
the_sn.post_note(ticket, note)
```
where `ticket` is a `Ticket` and `note` is a string.

### Assigning tickets

```python
the_sn.assign_myself(ticket)
```
Assign the current user to `ticket`. (Can we do this?)



## Data types

```python
from dataclass import dataclass

@dataclass
class Ticket:
    sys_id: str
    number: str
    opened_at: str # or date? 
    requested_for: str # The person's name
    u_category: str # Should always be "Research Services"
    u_sub_category: str # Should always be "Research Compute Platforms"
    short_description: str # Should always be Request access to HPC and cloud compute

@dataclass
class FullTicket(Ticket):
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
    start_date: str # NOTE!! the field is really `start_date-date`
    end_date: str # NOTES!! the field is really `end_date-date`
    data_sensitivity: str                              
    platform_justification: str                        
    research_justification: str                        
    computational_requirements: str                    
    users_who_require_access_names_and_emails: str     
    cost_compute_time_breakdown: str                   
```



# Thoughts on authentication methods

## Using an API token (current approach)

This seems to be the simplest approach.

### Setup process:

- IT setup permissions for the user to access the ServiceNow API, via MS Entra ID. This is a one-off process.
- The uses the Entra ID portal to generate an API token, which they can copy and paste into the CLI config. This is a one-off process.
- `rcpond` authenticates to the ServiceNow API using the token.

### Observations

- Actions taken by `rcpond` are not directly attributed to the user, but appear in the UI as being taken by "Research API User" (`research_cmd_user`). It is unclear where this name is configured, but it was probably setup by IT.
- It is possible for "Research API User" to create "work notes" and assign tickets to real users, so the token evidently has permissions to do these things.
- The `research_cmd_user` entity is clear distinct from the real user. It is unclear if how this would translate to using `rcpond` in production.
  - Given the small number of users who will have access to `rcpond`,  would it be acceptable for all actions taken by `rcpond` to be attributed to a single "service user" account? If so is the `research_cmd_user` account suitable for this? Are the limits that can be applied to this to prevent abuse? Particular on the scope of actions it can take.
- If not, would each user need to generate their own API token? If this acceptable level of hassle to impose on end-users? Would we need to coordinate with IT to ensure that each user has the correct permissions to generate a token and use it with `rcpond` and that it is possible to trace back each token's action to the original user?

- When assigning tickets, `rcpond` can assign them a real user, using that user's email address (as a string).
  -  If the email address is valid (for the ActiveDirectory), then ServiceNow correctly assigns the ticket to that user (including looking up the user's real name etc and displaying it in the UI).
  -  If the email address is invalid, then ServiceNow still assigns the ticket, and does not throw an error. This is a potential source of silent errors, As a ticket can be marked as assigned, but not actually be assigned to a real user.



## Other options to review:

- Make `rcpond` a OAuth client, and have users authenticate via a browser flow. This would be more complex to implement, but would allow actions to be directly attributed to the user.
- Other options? 


## Dynamic self-assignment options

For `rcpond` to assign tickets to the user running the command, it needs to be able to identify that user.

### Self-ID via API

Claude suggests various ways that might be possible, though not all of them are fully dynamic:

- Store user_sys_id directly in config. If the sys_id of the service account is stable, add it as a RCPOND_USER_SYS_ID config field and skip auto-discovery entirely. Most robust, zero extra API calls.
- Query sys_user by a known username. If the username of the account associated with the APIM subscription key is known (or can be stored in config as RCPOND_USER_NAME):

    ```
    params = {"sysparm_query": f"user_name={username}", "sysparm_fields": "sys_id", "sysparm_limit": "1"}
    resp = self.session.get(f"{self._base_url}/sys_user", params=params)
    ```

    This uses the already-working table path and a concrete query with no GlideScript.

- Try /api/now/v1/user or /api/now/ui/user_preference. Some ServiceNow instances expose endpoints that return the current session's user without needing a query. Worth checking whether your APIM gateway exposes either path — but this is speculative and may also 404.

Initial trials, suggest that even if valid, these tables/endpoints are not accessible with the `research_cmd_user` token.

### Self-ID via host environment

- If, and only if, `rcpond` is running on a Turing owned end-user machine, then it might be reasonable to expect the user's email address to be '`$USER`@turing.ac.uk'. If so, that this could provide a simple way to assign tickets to the user. It would be worth confirming with IT that this assumption is valid, and that there are no edge cases (e.g. users with non-standard email addresses) and if there is a way for `rcpond` to programmatically assert that it is running on a Turing owned machine.