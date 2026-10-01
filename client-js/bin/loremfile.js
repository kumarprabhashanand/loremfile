#!/usr/bin/env node
// The command npm installs, and the one `npx loremfile` runs. Everything is in src/; this file
// only turns main's answer into the process's exit code.
import { main } from "../src/cli.js";

process.exitCode = await main(process.argv.slice(2));
