# Notes and assumptions

`load_config()` should return either a dict or a data class (TBD)
`construct_prompt()` will need access to the config (in order to get the system
prompt, prompt template, available tools etc). It is not clear if should be passed
as a param (example here) or via an enclosing class, or some other means
Here the return value of `llm.generate` retunrs a LLMResponse object.
The `ServiceNow` class can either be an abstraction to:

- The main production ServiceNow instance
- The development ServiceNow instance
- A directory of scraped html files
  This could be controlled either by the configuration file/object and/or by using
  subclasses. Once initialised the caller should not have to care about the
  underlying data source

## To be done later

We should retrieve both assigned and unassigned tickets and be able to filter based on this.

Params:
        assigned_only:
            True : only include the tickets that have been assigned to the current individual user
            False : all tickets are "unassigned to an individual" but are "assigned to the current user's
                    assignment group"
