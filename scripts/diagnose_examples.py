#!/usr/bin/env python3
import os
import glob
import json
import re
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()


def check_env_vars(env_config):
    results = {}
    for key, value in env_config.items():
        matches = re.findall(r"\$\{([^}]+)\}", value)
        if matches:
            for var in matches:
                results[var] = os.environ.get(var) is not None
        else:
            results[key] = os.environ.get(value) is not None
    return results


def fetch_spec(url):
    try:
        r = requests.get(url)
        if r.status_code != 200:
            return None, f"HTTP status code: {r.status_code}"
        content = r.text
        try:
            spec = json.loads(content)
        except json.JSONDecodeError:
            try:
                spec = yaml.safe_load(content)
            except Exception as e:
                return None, f"Failed to parse as YAML: {e}"
        return spec, "Success"
    except Exception as e:
        return None, f"Error: {e}"


def analyze_example_file(file_path):
    report = {}
    report["file"] = file_path
    try:
        with open(file_path, "r") as f:
            config = json.load(f)
    except Exception as e:
        report["error"] = f"Failed to read JSON: {e}"
        return report
    mcp_servers = config.get("mcpServers", {})
    if not mcp_servers:
        report["error"] = "No mcpServers found"
        return report
    server_reports = {}
    for server, config_obj in mcp_servers.items():
        sub_report = {}
        env_config = config_obj.get("env", {})
        spec_url = env_config.get("OPENAPI_SPEC_URL", "Not Specified")
        sub_report["spec_url"] = spec_url
        spec, fetch_status = fetch_spec(spec_url)
        sub_report["curl_status"] = fetch_status
        if spec:
            if "openapi" in spec or "swagger" in spec:
                sub_report["spec_valid"] = True
            else:
                sub_report["spec_valid"] = False
        else:
            sub_report["spec_valid"] = False
        env_check = {}
        for key, value in env_config.items():
            if "${" in value:
                matches = re.findall(r"\$\{([^}]+)\}", value)
                for var in matches:
                    env_check[var] = os.environ.get(var) is not None
        sub_report["env_vars_set"] = env_check
        server_reports[server] = sub_report
    report["servers"] = server_reports
    return report


def print_markdown_report(report):
    print(f"\n### {os.path.basename(report['file'])}")
    if "error" in report:
        print(f"**Error:** {report['error']}")
        return
    print("| Server | Spec URL | HTTP Status | Spec Valid | Missing Env Vars |")
    print("|--------|----------|-------------|-----------|------------------|")
    for server, sub_report in report["servers"].items():
        spec_url = sub_report.get("spec_url", "-")
        curl_status = sub_report.get("curl_status", "-")
        spec_valid = "✅" if sub_report.get("spec_valid") else "❌"
        env_vars_set = sub_report.get("env_vars_set", {})
        missing_envs = ", ".join([k for k, v in env_vars_set.items() if not v]) or "-"
        print(
            f"| {server} | {spec_url} | {curl_status} | {spec_valid} | {missing_envs} |"
        )


def main():
    reports = []
    example_files = glob.glob("examples/*")
    for file_path in example_files:
        if not file_path.endswith(".json"):
            continue
        report = analyze_example_file(file_path)
        reports.append(report)
    for report in reports:
        print_markdown_report(report)


if __name__ == "__main__":
    main()
