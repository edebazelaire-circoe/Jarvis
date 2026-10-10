from pkg.util import helper


class Engine:
    def run(self, x):
        return helper(x)


def start(x):
    return Engine().run(x)
