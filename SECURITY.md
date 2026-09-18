# Security Policy

## Supported versions

This project is distributed as source code and has no published package release
yet. Security fixes are made on the latest default branch.

## Reporting a vulnerability

Do not report security vulnerabilities in public issues. Use GitHub's private
vulnerability reporting feature for this repository when it is available.

Please include:

- A clear description of the impact.
- The affected command, MCP tool, or code path.
- Reproduction steps or a minimal repository.
- Any workaround you have identified.

The maintainers use reports to investigate and prepare a fix before public
disclosure.

## Scope

CodeAtlas is a local CLI and MCP server. It reads local repository files and
writes its index under the selected project. Reports involving the parser,
storage, command execution, path handling, MCP boundary, or unexpected local
index state are in scope.
