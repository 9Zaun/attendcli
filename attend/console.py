"""Shared Rich console and small output helpers used across commands."""

from __future__ import annotations

from rich.console import Console

console = Console()


def info(msg: str) -> None:
    console.print(msg)


def success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")


def warn(msg: str) -> None:
    console.print(f"[yellow]{msg}[/yellow]")


def error(msg: str) -> None:
    console.print(f"[bold red]{msg}[/bold red]")


def rule(title: str = "") -> None:
    console.rule(title)
