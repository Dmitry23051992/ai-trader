from llm import LLM

llm = LLM()

reply = llm.ask(
    "Answer using exactly one word: READY"
)

print(reply)
