from core.context import Context


class Director:

    def __init__(self, iterations=3):
        self.pipeline = []
        self.iterations = iterations

    def register(self, agent):
        self.pipeline.append(agent)

    def run(self):

        for iteration in range(1, self.iterations + 1):

            print("\n" + "=" * 60)
            print(f"ITERATION {iteration}")
            print("=" * 60)

            ctx = Context()

            ctx.iteration = iteration

            for agent in self.pipeline:

                ctx.log(f"Running {agent.__class__.__name__}")

                ctx = agent.run(ctx)

        return ctx
