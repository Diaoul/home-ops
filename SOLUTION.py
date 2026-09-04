import re
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class RenovateUpdate:
    title: str
    branch: str
    pull_number: Optional[int] = None
    target: str = ""

@dataclass
class RenovateDashboard:
    open_prs: List[RenovateUpdate] = field(default_factory=list)
    detected_deps: List[str] = field(default_factory=list)
    raw_text: str = field(default="")

    def _parse(self):
        # Identify the main '## Open' section
        # Regex handles potential leading whitespace and the specific checkbox pattern
        open_pattern = r'## Open\s+(?:\n|$)'
        match = re.search(open_pattern, self.raw_text, re.IGNORECASE)
        
        if match:
            # Extract content after '## Open' until '## Detected' or end of block
            # Using a lookahead for the next major header
            open_content_start = match.end()
            open_content = self.raw_text[open_content_start:match.span(0)[1]] 
            
            # Iterate through lines to find the specific checkbox updates
            # We assume the list continues until a line that doesn't start with dash
            lines = open_content.split('\n')
            
            current_line = ""
            for line in lines:
                if line.startswith('-'):
                    current_line += line + '\n'
                else:
                    if current_line.strip():
                        self._process_open_pr(current_line.strip())
                    current_line = ""

            # Handle if the last line didn't trigger a newline immediately
            if current_line.strip():
                self._process_open_pr(current_line.strip())

        # Identify the '## Detected Dependencies' section
        deps_pattern = r'## Detected Dependencies'
        deps_match = re.search(deps_pattern, self.raw_text, re.IGNORECASE)

        if deps_match:
            # Capture content from the header down to the truncated list
            deps_start = deps_match.end()
            # Grab roughly the next 30 lines or until the end of the visible block
            # To handle the truncation gracefully, we scan for <details> tags
            raw_block = self.raw_text[deps_start:]
            
            # Extract <summary> blocks to get the meaningful titles
            details_pattern = r'<details><summary>(.*?)</summary>'
            found_details = re.findall(details_pattern, raw_block)
            
            for detail in found_details:
                # Sanitize the detail (remove leading/trailing whitespace from regex match)
                cleaned = detail.strip()
                self.detected_deps.append(cleaned)

    def _process_open_pr(self, line: str):
        # Pattern: - [ ] <!-- rebase-branch=NAME -->[TITLE](URL)
        match = re.search(r'- \[ \] <!-- rebase-branch=(.*?) -->\[(.*?)\]\((.*?)\)', line)
        
        if match:
            branch = match.group(1).strip()
            title = match.group(2).strip()
            link = match.group(3).strip()
            
            # Extract PR number from link like ../pull/8654
            pull_match = re.search(r'\.\./pull/(\d+)', link)
            pull_num = pull_match.group(1) if pull_match else None
            
            # Also try to capture the target object from the title
            # e.g. [fix(container): update image ghcr.io/...]
            target_obj = re.search(r'\[\w+\(container\):\s+(.+)\]', title)
            target = target_obj.group(1) if target_obj else ""

            self.open_prs.append(RenovateUpdate(
                title=title,
                branch=branch,
                pull_number=int(pull_num) if pull_num else None,
                target=target
            ))

    def __str__(self):
        lines = ["=== Renovate Dashboard Status ===", f"Open PRs: {len(self.open_prs)}", f"Detected Deps: {len(self.detected_deps)}"]
        for pr in self.open_prs:
            lines.append(f"  - {pr.title} (Branch: {pr.branch})")
        for dep in self.detected_deps[:5]:
            lines.append(f"  Dep: {dep}")
        return '\n'.join(lines)

    def get_rebase_branches(self) -> List[str]:
        """Return list of rebase branch names for iteration."""
        return [pr.branch for pr in self.open_prs if pr.branch]

if __name__ == "__main__":
    context_text = """
## Open
The following updates have all been created. To force a retry/rebase of any, click on a checkbox below.

 - [ ] <!-- rebase-branch=renovate/ghcr.io-open-webui-open-webui-v0.11.3 -->[fix(container): update image ghcr.io/open-webui/open-webui (751b617 ➔ d428020)](../pull/8654)
 - [ ] <!-- rebase-branch=renovate/ghcr.io-thelounge-thelounge-4.5.2 -->[fix(container): update image ghcr.io/thelounge/thelounge (7d073b3 ➔ 3cc5391)](../pull/8649)
 - [ ] <!-- rebase-branch=renovate/ghcr.io-ggml-org-llama.cpp-0.x -->[fix(container): update image ghcr.io/ggml-org/llama.cpp (server-vulkan-b10775 ➔ server-vulkan-b10795)](../pull/8650)
 - [ ] <!-- rebase-branch=renovate/ghcr.io-homeassistant-ai-ha-mcp-8.x -->[fix(container): update image ghcr.io/homeassistant-ai/ha-mcp (8.4.1 ➔ 8.4.2)](../pull/8651)
 - [ ] <!-- rebase-branch=renovate/ghcr.io-prometheus-community-charts-kube-prometheus-stack-89.x -->[fix(container): update image ghcr.io/prometheus-community/charts/kube-prometheus-stack (89.2.0 ➔ 89.2.2)](../pull/8653)
 - [ ] <!-- rebase-branch=renovate/ghcr.io-searxng-searxng-2026.x -->[fix(container): update image ghcr.io/searxng/searxng (2026.9.3-8f452ee89 ➔ 2026.9.4-15b0c8ef3)](../pull/8652)
 - [ ] <!-- rebase-branch=renovate/kubernetes -->[feat(container): update image ghcr.io/siderolabs/kubelet (v1.36.4 ➔ v1.37.0)](../pull/8602)
 - [ ] <!-- rebase-branch=renovate/talos -->[feat(container): update image siderolabs/talos (v1.13.9 ➔ v1.14.0)](../pull/8638)
 - [ ] <!-- rebase-branch=renovate/major-aqua-cilium-cilium-cli-0.x -->[feat(mise)!: Update tool aqua:cilium/cilium-cli (0.19.7 ➔ 0.20.0)](../pull/8584)
 - [ ] <!-- rebase-all-open-prs -->**Click on this checkbox to rebase all open PRs at once**

## Detected Dependencies

> [!NOTE]
> Detected dependencies section has been truncated

<details><summary>flux (83)</summary>
<blockquote>

<details><summary>kubernetes/apps/actions-runner-system/actions-runner-controller/app/ocirepository.yaml (1)</summary>

 - `ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller 0.14.2`

</details>

<details><summary>kubernetes/apps/ai/llmkube/app/ocirepository.yaml (1)</summary>

 - `ghcr.io/home-operations/charts-mirror/llmkube 0.9.24`

</details>

<details><summary>kubernetes/apps/ai/open-webui/app/helmrelease.yaml (1)</summary>

 - `ghcr.io/open-webui/open-webui v0.11.3@sha256:751b617714b91e4cfd0186a509c72480c858e012976103b09a30dad053c36175`

</details>

<details><summary>kubernetes/apps/cert-manager/cert-manager/app/ocirepository.yaml (1)</summary>

 - `quay.io/jetstack/charts/cert-manager v1.21.1`

</details>

<details><summary>kubernetes/apps/database/dragonfly/app/ocirepository.yaml (1)</summary>

 - `ghcr.io/dragonflydb/dragonfly-operator/helm/dragonfly-operator v1.6.1`

</details>

<details><summary>kubernetes/apps/default/miniflux/app/helmrelease.yaml (2)</summary>

 - `ghcr.io/home-operations/postgres-init 18.6@sha256:b6d3af974df781c673d37e49bdddfa14a6f5be28b18d2cb7713f0449be`
"""

    dashboard = RenovateDashboard(context_text.strip())
    
    # Print summary
    print(str(dashboard))
    print("\n--- Rebase Branches ---")
    print(dashboard.get_rebase_branches())
    
    # Trigger specific logic based on the state
    # Example: Iterate all open PRs
    for pr in dashboard.open_prs:
        if pr.pull_number and pr.pull_number > 8500: # Filter recent ones
            print(f"Recent Update: {pr.title}")