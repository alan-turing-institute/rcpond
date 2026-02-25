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
