# LLM.py


class LLM:
    def __init__(self, base_url: str | None, api_key: str | None) -> None:
        """Initialise the LLM class.

        Parameters
        ----------
        base_url : str | None
            The base URL of the OpenAI compatible API. If None, will load from environment variable `OPENAI_BASE_URL`.
        api_key : str | None
            The API key for the OpenAI compatible API. If None, will load from environment variable `OPENAI_API_KEY`.
        """

    def generate(self, prompt: str):
        """Generate a response from the LLM given a prompt.

        Parameters
        ----------
        prompt : str
            The prompt to generate a response for.

        Returns
        -------
        str
            The generated response from the LLM.
        """
