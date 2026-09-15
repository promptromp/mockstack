"""The ``mockstack`` command line: coloured help, and configuration errors without tracebacks.

A configuration mistake (an unknown flag, a missing or invalid setting, or a rules file
that does not load) is printed to stderr as ``mockstack: error: ...`` and exits with
status 2, as argparse does for usage errors. Settings are named the way a user sets
them: by flag, followed by the ``MOCKSTACK__*`` environment variables (also used in
``.env`` files) involved. Any other exception is a bug and keeps its traceback.

Help and errors are coloured with rich, which leaves colour out when the output is not a
terminal and honours ``NO_COLOR`` and ``FORCE_COLOR``.
"""

import argparse
import difflib
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import metadata
from string import Formatter
from typing import Any, Final, NoReturn

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails
from pydantic_settings import CLI_SUPPRESS, CliApp, CliSettingsSource, SettingsError
from rich.console import Console
from rich.text import Text
from rich_argparse import RichHelpFormatter

from mockstack.config import CliSettings, Settings, SettingsDependencyError
from mockstack.constants import ENV_NESTED_DELIMITER, ENV_PREFIX
from mockstack.strategies.proxyrules import RulesFileError


PROG: Final = "mockstack"

# argparse's exit status for usage errors, which a configuration error is too.
EXIT_USAGE_ERROR: Final = 2

# The exceptions reported as configuration errors; anything else keeps its traceback.
CONFIGURATION_ERRORS: Final = (ValidationError, SettingsError, RulesFileError)

# Flags and values are styled as --help styles them.
FLAG_STYLE: Final = RichHelpFormatter.styles["argparse.args"]
VALUE_STYLE: Final = RichHelpFormatter.styles["argparse.metavar"]
ERROR_STYLE: Final = "bold red"
NOTE_STYLE: Final = "dim"

DESCRIPTION: Final = (
    "An API-mocking server. The filefixtures strategy answers requests from Jinja templates; the proxyrules "
    "strategy follows a YAML rules file that serves fixtures, reverse-proxies or redirects."
)
EPILOG: Final = (
    "Every option can also be set with a MOCKSTACK__* environment variable or in a .env file, e.g. "
    "MOCKSTACK__TEMPLATES_DIR. See https://promptromp.github.io/mockstack/configuration/"
)


@dataclass(frozen=True)
class SettingName:
    """How a user sets one setting: its flag, if it has one, and its environment variable."""

    flag: str | None
    env_var: str

    @property
    def display(self) -> str:
        """The flag, or the environment variable of a setting without one."""
        return self.flag or self.env_var


@dataclass
class ErrorReport:
    """A configuration error as printed: its problems, the settings they name, hints, and
    whether to point at ``--help``."""

    problems: list[Text]
    settings: list[SettingName] = field(default_factory=list)
    hints: list[Text] = field(default_factory=list)
    help_hint: bool = True


class CliArgumentParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` with rich-formatted help whose usage errors are printed like
    every other configuration error, without the usage text."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(formatter_class=RichHelpFormatter, **kwargs)

    def parse_args_suggesting_flags(
        self, args: Sequence[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        """``parse_args``, suggesting the closest known flag for an unrecognized one."""
        parsed, unrecognized = self.parse_known_args(args, namespace)
        if unrecognized:
            problem = Text(f"unrecognized arguments: {' '.join(unrecognized)}")
            self.exit_with(ErrorReport([problem], hints=self._flag_suggestions(unrecognized)))
        return parsed

    def error(self, message: str) -> NoReturn:
        self.exit_with(ErrorReport([Text(message)]))

    def exit_with(self, report: ErrorReport) -> NoReturn:
        """Print ``report`` and exit with the usage error status."""
        print_report(self.prog, report)
        self.exit(EXIT_USAGE_ERROR)

    def _flag_suggestions(self, arguments: Sequence[str]) -> list[Text]:
        known = [option for option in self._option_string_actions if option.startswith("--")]
        hints = []
        for argument in arguments:
            flag = argument.split("=", 1)[0]
            matches = difflib.get_close_matches(flag, known, n=1) if flag.startswith("--") else []
            if matches:
                hints.append(Text.assemble(f"{flag}: did you mean ", (matches[0], FLAG_STYLE), "?"))
        return hints


def build_parser() -> CliArgumentParser:
    """The ``mockstack`` parser with ``--version``; pydantic-settings adds the settings' flags."""
    parser = CliArgumentParser(prog=PROG, description=DESCRIPTION, epilog=EPILOG)
    parser.add_argument("--version", action="version", version=f"%(prog)s {metadata.version('mockstack')}")
    return parser


def parse_settings(parser: CliArgumentParser, argv: Sequence[str] | None = None) -> CliSettings:
    """Settings from ``argv`` (by default the command line), environment variables and ``.env``."""
    source: CliSettingsSource[CliArgumentParser] = CliSettingsSource(
        CliSettings,
        root_parser=parser,
        parse_args_method=CliArgumentParser.parse_args_suggesting_flags,
    )
    return CliApp.run(CliSettings, cli_args=None if argv is None else list(argv), cli_settings_source=source)


def report_for(exc: Exception) -> ErrorReport:
    """The report for one of ``CONFIGURATION_ERRORS``."""
    if isinstance(exc, ValidationError):
        return _validation_report(exc)
    if isinstance(exc, RulesFileError):
        return ErrorReport([Text.assemble((str(exc.path), "bold"), f": {exc.problem}")], help_hint=False)
    cause = f": {exc.__cause__}" if exc.__cause__ is not None else ""
    return ErrorReport([Text(f"{exc}{cause}")])


def print_report(prog: str, report: ErrorReport) -> None:
    """Print ``report`` to stderr, coloured when stderr is a terminal."""
    console = Console(stderr=True, soft_wrap=True, highlight=False)
    heading = Text.assemble((f"{prog}: ", "bold"), ("error: ", ERROR_STYLE))
    if len(report.problems) == 1:
        console.print(heading + report.problems[0])
    else:
        console.print(heading + f"{len(report.problems)} invalid settings")
        for problem in report.problems:
            console.print(Text("  ") + problem)

    env_vars = dict.fromkeys(name.env_var for name in report.settings if name.flag is not None)
    if env_vars:
        names = Text(", ").join(Text(env_var, style=FLAG_STYLE) for env_var in env_vars)
        console.print(Text.assemble("  ", ("environment or .env: ", NOTE_STYLE), names))
    for hint in report.hints:
        console.print(Text("  ") + hint)
    if report.help_hint:
        console.print(Text(f"Run '{prog} --help' to see all options.", style=NOTE_STYLE))


def setting_path(loc: Sequence[int | str]) -> tuple[str, ...]:
    """The settings at the start of a pydantic error location, e.g. ``("opentelemetry", "enabled")``.

    Empty for an error about the settings as a whole.
    """
    path: list[str] = []
    model: type[BaseModel] | None = Settings
    for part in loc:
        if model is None or not isinstance(part, str) or part not in model.model_fields:
            break
        path.append(part)
        model = _settings_group(model.model_fields[part])
    return tuple(path)


def setting_name(path: Sequence[str]) -> SettingName:
    """Name the setting at ``path``, a sequence of ``Settings`` field names.

    A flag is the path in kebab case joined with dots, as pydantic-settings generates it.
    A setting hidden from the command line has none, and neither has a settings group
    such as ``opentelemetry``: only the settings inside it do.
    """
    has_flag = True
    model: type[BaseModel] | None = Settings
    for name in path:
        if model is None:
            raise ValueError(f"not a setting: {'.'.join(path)}")
        field_info = model.model_fields[name]
        has_flag = has_flag and CLI_SUPPRESS not in field_info.metadata
        model = _settings_group(field_info)

    flag = "--" + ".".join(name.replace("_", "-") for name in path) if has_flag and model is None else None
    return SettingName(flag=flag, env_var=(ENV_PREFIX + ENV_NESTED_DELIMITER.join(path)).upper())


def _settings_group(field_info: FieldInfo) -> type[BaseModel] | None:
    """The model of a field that groups further settings, or ``None`` for a plain setting."""
    annotation = field_info.annotation
    return annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None


def _validation_report(exc: ValidationError) -> ErrorReport:
    report = ErrorReport(problems=[])
    for error in exc.errors(include_url=False):
        cause = error.get("ctx", {}).get("error")
        if isinstance(cause, SettingsDependencyError):
            problem, names = _dependency_problem(cause)
        else:
            problem, names = _field_problem(error)
        report.problems.append(problem)
        report.settings.extend(names)
    return report


def _dependency_problem(error: SettingsDependencyError) -> tuple[Text, list[SettingName]]:
    """The error's template with each setting named as it is set."""
    text = Text()
    names: list[SettingName] = []
    for literal, field_name, _, _ in Formatter().parse(error.template):
        text.append(literal)
        if field_name:
            name = setting_name((field_name,))
            names.append(name)
            text.append(name.display, style=FLAG_STYLE)
    return text, names


def _field_problem(error: ErrorDetails) -> tuple[Text, list[SettingName]]:
    """E.g. ``invalid value 'abc' for --port: input should be a valid integer``."""
    message = _clause(error["msg"])
    path = setting_path(error["loc"])
    if not path:
        return Text(message), []

    name = setting_name(path)
    text = Text()
    if error["type"] != "missing" and isinstance(error["input"], str | int | float):
        text.append("invalid value ")
        text.append(repr(error["input"]), style=VALUE_STYLE)
        text.append(" for ")
    text.append(name.display, style=FLAG_STYLE)
    text.append(f": {message}")
    return text, [name]


def _clause(message: str) -> str:
    """A pydantic error message as a clause: without its ``Value error, `` prefix, and with
    the first word lower-cased unless it is an acronym."""
    message = message.removeprefix("Value error, ")
    return message[:1].lower() + message[1:] if message[1:2].islower() else message
