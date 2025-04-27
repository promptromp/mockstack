"""MockStack strategy that will randomize output with emphasis on invalid responses."""

from fastapi import Request, Response

from mockstack.strategies.base import BaseStrategy


class ChaosMonkeyStrategy(BaseStrategy):
    """Strategy for randomizing output with emphasis on invalid responses."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def apply(self, request: Request, response: Response) -> None:
        pass
