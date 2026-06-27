from dataclasses import dataclass, field


@dataclass
class Context:
    market: dict = field(default_factory=dict)
    strategy: dict = field(default_factory=dict)
    backtest: dict = field(default_factory=dict)
    learning: dict = field(default_factory=dict)

    candidate_name: str = ""

    logs: list = field(default_factory=list)

    def log(self, message: str):
        print(message)
        self.logs.append(message)
