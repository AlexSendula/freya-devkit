#!/usr/bin/env python3
"""
Code Graph Operations

Build and query dependency graphs for code impact analysis.

Usage:
    python graph_ops.py --build [--dir /path/to/project]
    python graph_ops.py --update [--commit HEAD~1]
    python graph_ops.py --query src/lib/auth.ts
    python graph_ops.py --impact src/lib/auth.ts
    python graph_ops.py --dependents src/lib/auth.ts
    python graph_ops.py --dependencies src/lib/auth.ts
    python graph_ops.py --clear
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Any


# File patterns by language
FILE_PATTERNS = {
    'typescript': ['**/*.ts', '**/*.tsx'],
    'javascript': ['**/*.js', '**/*.jsx'],
    'python': ['**/*.py'],
    'go': ['**/*.go'],
}

# Category patterns
CATEGORY_PATTERNS = {
    'auth': ['**/auth/**', '**/middleware/auth*', '**/authentication/**'],
    'api': ['**/api/**', '**/routes/**', '**/controllers/**', '**/handlers/**'],
    'data': ['**/models/**', '**/schema/**', '**/db/**', '**/entities/**'],
    'ui': ['**/components/**', '**/pages/**', '**/views/**', '**/screens/**'],
    'infra': ['**/infra/**', '**/deploy/**', '**/infrastructure/**'],
    'util': ['**/utils/**', '**/lib/**', '**/helpers/**', '**/common/**'],
    'config': ['**/*.config.*', '**/config/**'],
    'test': ['**/*.test.*', '**/*.spec.*', '**/__tests__/**', '**/test/**', '**/tests/**'],
}

# Import patterns by language
IMPORT_PATTERNS = {
    'typescript': [
        # import { x } from './y'
        r'import\s+\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]',
        # import x from './y'
        r'import\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        # import * as x from './y'
        r'import\s+\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        # export * from './y'
        r'export\s+(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]',
        # require('./y')
        r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        # import('./y')
        r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
    ],
    'javascript': [
        # Same as TypeScript (JS is subset)
        r'import\s+\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'import\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'import\s+\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'export\s+(?:\*|\{[^}]*\})\s+from\s+[\'"]([^\'"]+)[\'"]',
        r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
    ],
    'python': [
        # from x import y
        r'from\s+([\w.]+)\s+import',
        # import x
        r'^import\s+([\w.]+)',
        # from . import x
        r'from\s+\.(\s+import|\s*\.\s*[\w.]*\s+import)',
    ],
    'go': [
        # import "module/path"
        r'import\s+[\'"]([^\'"]+)[\'"]',
        # import alias "module/path"
        r'import\s+\w+\s+[\'"]([^\'"]+)[\'"]',
        # multi-line import ( ... )
        r'[\'"]([^\'"]+)[\'"]',
    ],
}

# Export patterns by language
EXPORT_PATTERNS = {
    'typescript': [
        r'export\s+(?:async\s+)?function\s+(\w+)',
        r'export\s+const\s+(\w+)',
        r'export\s+class\s+(\w+)',
        r'export\s+interface\s+(\w+)',
        r'export\s+type\s+(\w+)',
        r'export\s+enum\s+(\w+)',
        r'export\s+\{([^}]+)\}',
    ],
    'javascript': [
        r'export\s+(?:async\s+)?function\s+(\w+)',
        r'export\s+const\s+(\w+)',
        r'export\s+class\s+(\w+)',
        r'export\s+\{([^}]+)\}',
        r'module\.exports\s*=\s*\{([^}]+)\}',
        r'exports\.(\w+)\s*=',
    ],
    'python': [
        # Python doesn't have explicit exports, but we can track __all__
        r'__all__\s*=\s*\[([^\]]+)\]',
    ],
    'go': [
        # Go exports are capitalised functions/types
        r'func\s+([A-Z]\w+)',
        r'type\s+([A-Z]\w+)',
        r'var\s+([A-Z]\w+)',
        r'const\s+([A-Z]\w+)',
    ],
}


class CodeGraph:
    """Manages the dependency graph for a codebase."""

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = Path(project_dir or os.getcwd()).resolve()
        self.graph_dir = self.project_dir / 'docs' / '.code-graph'
        self.graph_path = self.graph_dir / 'graph.json'
        self.classifications_path = self.graph_dir / 'classifications.json'
        self.graph: Dict[str, Any] = {}
        self.classifications: Dict[str, Any] = {}

    def _get_git_commit(self) -> Optional[str]:
        """Get current git commit hash."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:12]
        except Exception:
            pass
        return None

    def _get_changed_files(self, since_commit: str) -> List[str]:
        """Get list of files changed since a commit."""
        try:
            result = subprocess.run(
                ['git', 'diff', f'{since_commit}..HEAD', '--name-only'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
        except Exception:
            pass
        return []

    def _detect_language(self, file_path: Path) -> Optional[str]:
        """Detect language from file extension."""
        ext = file_path.suffix.lower()
        mapping = {
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.py': 'python',
            '.go': 'go',
        }
        return mapping.get(ext)

    def _categorize_file(self, file_path: str) -> str:
        """Infer category from file path."""
        from fnmatch import fnmatch

        for category, patterns in CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if fnmatch(file_path, pattern):
                    return category
        return 'unknown'

    def _resolve_import_path(self, import_path: str, from_file: str) -> Optional[str]:
        """Resolve an import path to a project-relative file path."""
        # External package
        if not import_path.startswith('.') and not import_path.startswith('/'):
            # Check if it might be a local package
            parts = import_path.split('/')
            if len(parts) > 1:
                # Could be a scoped package or monorepo package
                potential_local = self.project_dir / 'node_modules' / import_path
                if potential_local.exists():
                    return None  # It's external
            return None  # External package

        # Relative import
        from_dir = Path(from_file).parent
        resolved = (from_dir / import_path).resolve()

        # Try to find the actual file
        candidates = [
            resolved,
            resolved.with_suffix('.ts'),
            resolved.with_suffix('.tsx'),
            resolved.with_suffix('.js'),
            resolved.with_suffix('.jsx'),
            resolved.with_suffix('.py'),
            resolved / 'index.ts',
            resolved / 'index.tsx',
            resolved / 'index.js',
            resolved / 'index.jsx',
            resolved / '__init__.py',
        ]

        for candidate in candidates:
            try:
                rel = candidate.relative_to(self.project_dir)
                if candidate.exists():
                    return str(rel)
            except ValueError:
                continue

        return None

    def _parse_imports(self, content: str, language: str) -> List[str]:
        """Extract import paths from file content."""
        imports = []
        patterns = IMPORT_PATTERNS.get(language, [])

        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1] if len(match) > 1 else ''
                if match:
                    imports.append(match.strip())

        return list(set(imports))

    def _parse_exports(self, content: str, language: str) -> List[str]:
        """Extract export names from file content."""
        exports = []
        patterns = EXPORT_PATTERNS.get(language, [])

        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0] if match[0] else match[1] if len(match) > 1 else ''
                if match:
                    # Handle export { a, b, c } syntax
                    for name in match.split(','):
                        name = name.strip().split(' as ')[-1].strip()
                        if name and name not in exports:
                            exports.append(name)
                elif isinstance(match, str) and match:
                    if match not in exports:
                        exports.append(match)

        return list(set(exports))

    def _parse_gitignore(self) -> List[str]:
        """Parse .gitignore and return list of patterns to exclude."""
        gitignore_path = self.project_dir / '.gitignore'
        patterns = []

        if gitignore_path.exists():
            try:
                content = gitignore_path.read_text(encoding='utf-8')
                for line in content.splitlines():
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    # Skip negation patterns (we just want exclusions)
                    if line.startswith('!'):
                        continue
                    # Clean up the pattern for simple matching
                    # Remove leading/trailing slashes for directory matching
                    pattern = line.strip('/')
                    # Handle ** patterns - just use the base name
                    if '**' in pattern:
                        pattern = pattern.replace('**/', '').replace('/**', '')
                    # Handle *.ext patterns - extract the extension part
                    if pattern.startswith('*.'):
                        patterns.append(pattern)
                    else:
                        patterns.append(pattern)
            except Exception:
                pass

        return patterns

    def _get_exclusion_rules(self) -> Dict[str, Any]:
        """Get comprehensive exclusion rules for the project."""
        return {
            # Directories that are ALWAYS excluded (build artifacts, dependencies, etc.)
            'always_exclude_dirs': {
                # Dependencies
                'node_modules', 'vendor', '__pycache__', 'venv', '.venv', 'env',
                # Version control
                '.git', '.svn', '.hg',
                # Build outputs
                'dist', 'build', 'out', '.output', 'target',
                # Framework build caches
                '.next', '.nuxt', '.astro', '.svelte-kit', '.remix', '.vuepress',
                '.docusaurus', '.cache', '.parcel-cache', '.vite', '.turbo',
                # Test coverage
                'coverage', '.nyc_output', 'htmlcov',
                # IDE/Editor
                '.idea', '.vscode', '.sublime-project',
                # OS files
                '__MACOSX',
                # Generated code
                'generated', '.generated', 'autogen',
                # Documentation builds
                '_site', '.docusaurus',
                # Other common exclusions
                '.github', '.gitlab', 'scripts', 'docs', 'examples',
            },
            # File patterns that are ALWAYS excluded
            'always_exclude_files': {
                '*.d.ts',        # TypeScript declaration files
                '*.min.js',      # Minified JS
                '*.min.css',     # Minified CSS
                '*.bundle.js',   # Bundled JS
                '*.chunk.js',    # Webpack chunks
                '*.map',         # Source maps
                '*.lock',        # Lock files
                '*.log',         # Log files
            },
            # Directories that are LIKELY source code (whitelist approach)
            'likely_source_dirs': {
                # JavaScript/TypeScript
                'src', 'lib', 'app', 'apps', 'packages', 'components', 'pages',
                'hooks', 'utils', 'helpers', 'services', 'contexts', 'stores',
                'types', 'interfaces', 'models', 'schemas',
                # Python
                'app', 'apps', 'backend', 'api', 'core', 'modules',
                # Go
                'cmd', 'pkg', 'internal', 'api', 'handler', 'handlers',
                # General
                'server', 'client', 'shared', 'common', 'config',
            },
        }

    def _detect_source_structure(self) -> List[str]:
        """Detect which source directories exist in the project."""
        rules = self._get_exclusion_rules()
        found_source_dirs = []

        for dir_name in rules['likely_source_dirs']:
            dir_path = self.project_dir / dir_name
            if dir_path.exists() and dir_path.is_dir():
                found_source_dirs.append(dir_name)

        return found_source_dirs

    def _should_exclude(self, rel_path: str, gitignore_patterns: List[str]) -> bool:
        """Check if a path should be excluded based on multiple rules."""
        from fnmatch import fnmatch

        rules = self._get_exclusion_rules()
        path_parts = Path(rel_path).parts
        filename = Path(rel_path).name

        # 1. Check always-exclude directories (anywhere in path)
        for exc_dir in rules['always_exclude_dirs']:
            if exc_dir in path_parts:
                return True

        # 2. Check always-exclude file patterns
        for pattern in rules['always_exclude_files']:
            if fnmatch(filename, pattern):
                return True

        # 3. Check gitignore patterns
        for pattern in gitignore_patterns:
            # Handle *.ext patterns
            if pattern.startswith('*.'):
                if fnmatch(filename, pattern):
                    return True
            # Handle directory/file name patterns
            elif pattern in path_parts:
                return True
            # Handle glob-like patterns
            elif fnmatch(rel_path, f'*{pattern}*'):
                return True

        return False

    # =========================================================================
    # Hybrid Classification System (Rules + AI)
    # =========================================================================

    def _get_project_context(self) -> Dict[str, Any]:
        """Detect project type, framework, and language for context."""
        context = {
            'framework': None,
            'language': None,
            'package_manager': None,
            'config_files': [],
        }

        # Check for config files
        config_files = {
            'package.json': 'node',
            'tsconfig.json': 'typescript',
            'pyproject.toml': 'python',
            'setup.py': 'python',
            'requirements.txt': 'python',
            'go.mod': 'go',
            'Cargo.toml': 'rust',
        }

        for config_file, hint in config_files.items():
            if (self.project_dir / config_file).exists():
                context['config_files'].append(config_file)
                if hint in ['node', 'typescript']:
                    context['language'] = context['language'] or 'typescript'
                    context['package_manager'] = 'npm/yarn/pnpm'
                elif hint == 'python':
                    context['language'] = context['language'] or 'python'
                    context['package_manager'] = 'pip'
                elif hint == 'go':
                    context['language'] = 'go'
                    context['package_manager'] = 'go modules'

        # Detect framework from package.json
        package_json_path = self.project_dir / 'package.json'
        if package_json_path.exists():
            try:
                content = package_json_path.read_text(encoding='utf-8')
                package_data = json.loads(content)
                deps = {**package_data.get('dependencies', {}), **package_data.get('devDependencies', {})}

                if 'next' in deps:
                    context['framework'] = 'Next.js'
                elif 'nuxt' in deps:
                    context['framework'] = 'Nuxt.js'
                elif 'react' in deps:
                    context['framework'] = 'React'
                elif 'vue' in deps:
                    context['framework'] = 'Vue'
                elif 'svelte' in deps:
                    context['framework'] = 'Svelte'
                elif 'express' in deps:
                    context['framework'] = 'Express'
                elif 'fastapi' in deps or any('fastapi' in d for d in deps):
                    context['framework'] = 'FastAPI'
            except Exception:
                pass

        # Check for framework-specific config files
        if (self.project_dir / 'next.config.js').exists() or (self.project_dir / 'next.config.mjs').exists():
            context['framework'] = 'Next.js'
        if (self.project_dir / 'nuxt.config.js').exists() or (self.project_dir / 'nuxt.config.ts').exists():
            context['framework'] = 'Nuxt.js'

        return context

    def _get_all_directories(self, max_depth: int = 2) -> List[str]:
        """Get all directories in the project up to max_depth."""
        directories = []

        for item in self.project_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                directories.append(item.name)
                # Get subdirectories if within max_depth
                if max_depth > 1:
                    try:
                        for subitem in item.iterdir():
                            if subitem.is_dir():
                                directories.append(f"{item.name}/{subitem.name}")
                    except PermissionError:
                        pass

        return sorted(set(directories))

    def _load_classifications(self) -> Dict[str, Any]:
        """Load cached classifications from file."""
        if self.classifications_path.exists():
            try:
                with open(self.classifications_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {'version': 1, 'directories': {}}

    def _save_classifications(self, classifications: Dict[str, Any]) -> None:
        """Save classifications to file."""
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        classifications['version'] = 1
        classifications['classified_at'] = datetime.now(timezone.utc).isoformat()
        with open(self.classifications_path, 'w') as f:
            json.dump(classifications, f, indent=2)

    def _classify_with_rules(self, dir_name: str) -> Optional[Dict[str, Any]]:
        """Classify a directory using known rules. Returns None if unknown."""
        rules = self._get_exclusion_rules()

        # Check if it's a known exclude directory
        if dir_name in rules['always_exclude_dirs']:
            return {'type': 'exclude', 'confidence': 1.0, 'source': 'rule'}

        # Check if it's a known source directory
        if dir_name in rules['likely_source_dirs']:
            return {'type': 'source', 'confidence': 1.0, 'source': 'rule'}

        # Check gitignore patterns
        gitignore_patterns = self._parse_gitignore()
        for pattern in gitignore_patterns:
            if pattern == dir_name or pattern in dir_name:
                return {'type': 'exclude', 'confidence': 0.9, 'source': 'gitignore'}

        return None

    def _build_classification_prompt(self, unknown_dirs: List[str], context: Dict[str, Any]) -> str:
        """Build the AI prompt for classifying unknown directories."""
        context_str = f"""Project context:
- Framework: {context.get('framework') or 'Unknown'}
- Language: {context.get('language') or 'Unknown'}
- Package manager: {context.get('package_manager') or 'Unknown'}
- Config files: {', '.join(context.get('config_files', []))}"""

        dirs_str = '\n'.join(f"- {d}/" for d in unknown_dirs)

        return f"""You are classifying directories in a codebase for dependency graph analysis.

{context_str}

Classify these directories as 'source' (contains code to track for dependencies) or 'exclude' (generated/build/vendor/should not track):

{dirs_str}

Respond with ONLY a JSON object, no markdown formatting:
{{"directory_name": {{"type": "source|exclude", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}, ...}}"""

    def _parse_ai_classification_response(self, response: str, unknown_dirs: List[str]) -> Dict[str, Dict[str, Any]]:
        """Parse AI response into classification dict."""
        try:
            # Try to extract JSON from response
            response = response.strip()
            # Remove markdown code blocks if present
            if response.startswith('```'):
                response = response.split('\n', 1)[1]
            if response.endswith('```'):
                response = response.rsplit('\n', 1)[0]

            result = json.loads(response)
            classifications = {}

            for dir_name in unknown_dirs:
                if dir_name in result:
                    data = result[dir_name]
                    classifications[dir_name] = {
                        'type': data.get('type', 'exclude'),
                        'confidence': float(data.get('confidence', 0.5)),
                        'source': 'ai',
                        'reasoning': data.get('reasoning', ''),
                    }
                else:
                    # Default to exclude if AI didn't classify
                    classifications[dir_name] = {
                        'type': 'exclude',
                        'confidence': 0.5,
                        'source': 'default',
                        'reasoning': 'Not classified by AI',
                    }

            return classifications
        except json.JSONDecodeError:
            # If parsing fails, default all to exclude
            return {
                dir_name: {
                    'type': 'exclude',
                    'confidence': 0.3,
                    'source': 'error',
                    'reasoning': 'Failed to parse AI response',
                }
                for dir_name in unknown_dirs
            }

    def _classify_with_ai(self, unknown_dirs: List[str], context: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Send unknown directories to AI for classification.

        NOTE: This method is designed to be called by the skill (which has AI access).
        When run standalone via CLI, it will return default classifications.
        """
        # When run via CLI without AI, return default exclude classifications
        # The skill will intercept this and call AI properly
        return {
            dir_name: {
                'type': 'exclude',
                'confidence': 0.5,
                'source': 'no_ai',
                'reasoning': 'AI classification not available in CLI mode',
            }
            for dir_name in unknown_dirs
        }

    def _ask_user_classification(self, dir_name: str, classification: Dict[str, Any]) -> str:
        """Ask user to confirm classification for low-confidence results."""
        print(f"\nUncertain classification for '{dir_name}/'")
        print(f"  AI suggests: {classification['type']} ({int(classification['confidence'] * 100)}% confidence)")
        print(f"  Reasoning: {classification.get('reasoning', 'No reasoning provided')}")
        print()
        print("  [1] Source - include in dependency graph")
        print("  [2] Exclude - skip this directory")

        while True:
            try:
                choice = input("  Your choice (1 or 2): ").strip()
                if choice == '1':
                    return 'source'
                elif choice == '2':
                    return 'exclude'
                else:
                    print("  Please enter 1 or 2")
            except EOFError:
                # Non-interactive mode, default to exclude
                return 'exclude'

    def _classify_directories(self, use_ai: bool = True, ai_response: Optional[str] = None) -> Dict[str, Any]:
        """Main classification flow: rules → AI → user confirmation.

        Args:
            use_ai: Whether to use AI for unknown directories
            ai_response: Pre-fetched AI response (from skill invocation)

        Returns:
            Classifications dict with all directories classified
        """
        classifications = self._load_classifications()
        context = self._get_project_context()
        all_dirs = self._get_all_directories()

        # Find directories that need classification
        known_classifications = classifications.get('directories', {})
        dirs_to_classify = []

        for dir_name in all_dirs:
            # Check if already classified
            if dir_name in known_classifications:
                continue

            # Try rules first
            rule_result = self._classify_with_rules(dir_name)
            if rule_result:
                known_classifications[dir_name] = rule_result
            else:
                dirs_to_classify.append(dir_name)

        # If no unknown directories, we're done
        if not dirs_to_classify:
            classifications['directories'] = known_classifications
            classifications['project_context'] = context
            self._save_classifications(classifications)
            return classifications

        # Classify unknowns with AI
        if use_ai:
            if ai_response:
                # Use pre-fetched AI response
                ai_classifications = self._parse_ai_classification_response(ai_response, dirs_to_classify)
            else:
                # Get AI classification (will return defaults in CLI mode)
                ai_classifications = self._classify_with_ai(dirs_to_classify, context)

            # Process AI results
            for dir_name, classification in ai_classifications.items():
                confidence = classification.get('confidence', 0)

                if confidence >= 0.8:
                    # Auto-accept high confidence
                    known_classifications[dir_name] = classification
                else:
                    # Ask user for low confidence
                    final_type = self._ask_user_classification(dir_name, classification)
                    known_classifications[dir_name] = {
                        'type': final_type,
                        'confidence': 1.0,
                        'source': 'user',
                        'reasoning': f"User confirmed after AI suggestion ({classification['type']})",
                    }
        else:
            # No AI, default unknown to exclude
            for dir_name in dirs_to_classify:
                known_classifications[dir_name] = {
                    'type': 'exclude',
                    'confidence': 0.5,
                    'source': 'default',
                    'reasoning': 'No AI available, defaulted to exclude',
                }

        # Save and return
        classifications['directories'] = known_classifications
        classifications['project_context'] = context
        self._save_classifications(classifications)
        return classifications

    # =========================================================================
    # Public methods for skill integration (AI-assisted classification)
    # =========================================================================

    def needs_classification(self) -> bool:
        """Check if there are directories that need AI classification."""
        classifications = self._load_classifications()
        all_dirs = self._get_all_directories()
        known_classifications = classifications.get('directories', {})

        for dir_name in all_dirs:
            if dir_name not in known_classifications:
                rule_result = self._classify_with_rules(dir_name)
                if not rule_result:
                    return True
        return False

    def get_unclassified_directories(self) -> List[str]:
        """Get list of directories that need AI classification."""
        classifications = self._load_classifications()
        all_dirs = self._get_all_directories()
        known_classifications = classifications.get('directories', {})

        unclassified = []
        for dir_name in all_dirs:
            if dir_name not in known_classifications:
                rule_result = self._classify_with_rules(dir_name)
                if not rule_result:
                    unclassified.append(dir_name)

        return unclassified

    def get_classification_prompt(self) -> str:
        """Get the prompt to send to AI for classification."""
        unknown_dirs = self.get_unclassified_directories()
        if not unknown_dirs:
            return ""
        context = self._get_project_context()
        return self._build_classification_prompt(unknown_dirs, context)

    def classify_with_ai_response(self, ai_response: str) -> Dict[str, Any]:
        """Process AI response and complete classification.

        This is called by the skill after it gets AI response.
        Returns classifications with any low-confidence items needing user input.
        """
        return self._classify_directories(use_ai=True, ai_response=ai_response)

    def get_low_confidence_classifications(self) -> Dict[str, Dict[str, Any]]:
        """Get classifications that need user confirmation."""
        classifications = self._load_classifications()
        low_confidence = {}

        for dir_name, info in classifications.get('directories', {}).items():
            if info.get('source') == 'ai' and info.get('confidence', 0) < 0.8:
                low_confidence[dir_name] = info

        return low_confidence

    def set_classification(self, dir_name: str, classification_type: str, reasoning: str = "") -> None:
        """Set classification for a directory (used after user confirmation)."""
        classifications = self._load_classifications()
        classifications.setdefault('directories', {})[dir_name] = {
            'type': classification_type,
            'confidence': 1.0,
            'source': 'user',
            'reasoning': reasoning,
        }
        self._save_classifications(classifications)

    def _scan_files(self, classifications: Optional[Dict[str, Any]] = None) -> List[Path]:
        """Find all source files in the project using classifications."""
        files = []
        gitignore_patterns = self._parse_gitignore()

        # Use classifications if provided, otherwise load from file
        if classifications is None:
            classifications = self._load_classifications()

        classified_dirs = classifications.get('directories', {})

        # Get source directories from classifications
        source_dirs = [
            d for d, info in classified_dirs.items()
            if info.get('type') == 'source' and '/' not in d  # Only top-level dirs
        ]

        if source_dirs:
            # Scan only classified source directories
            for src_dir in source_dirs:
                dir_path = self.project_dir / src_dir
                for language, patterns in FILE_PATTERNS.items():
                    for pattern in patterns:
                        files.extend(dir_path.glob(pattern))

            # Also scan root-level source files (e.g., index.ts, app.ts)
            for language, patterns in FILE_PATTERNS.items():
                for pattern in patterns:
                    for f in self.project_dir.glob(pattern):
                        # Only include if it's directly in root (no subdirectory)
                        if len(Path(f.relative_to(self.project_dir)).parts) == 1:
                            files.append(f)
        else:
            # Fallback: scan entire project but apply filters
            for language, patterns in FILE_PATTERNS.items():
                for pattern in patterns:
                    files.extend(self.project_dir.glob(pattern))

        # Apply exclusion rules and check against classifications
        filtered = []
        for f in files:
            try:
                rel_path = str(f.relative_to(self.project_dir))
                # Check if path is in an excluded directory
                top_level_dir = rel_path.split('/')[0] if '/' in rel_path else None

                # Skip if in an excluded directory (from classifications)
                if top_level_dir and top_level_dir in classified_dirs:
                    if classified_dirs[top_level_dir].get('type') == 'exclude':
                        continue

                # Also check standard exclusion rules
                if not self._should_exclude(rel_path, gitignore_patterns):
                    filtered.append(f)
            except ValueError:
                continue

        # Remove duplicates
        return list(set(filtered))

    def _build_file_info(self, file_path: Path) -> Dict[str, Any]:
        """Build file info dict for a single file."""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return {'imports': [], 'dependents': [], 'exports': []}

        language = self._detect_language(file_path)
        rel_path = str(file_path.relative_to(self.project_dir))

        imports = self._parse_imports(content, language) if language else []
        exports = self._parse_exports(content, language) if language else []

        # Resolve import paths
        resolved_imports = []
        for imp in imports:
            resolved = self._resolve_import_path(imp, rel_path)
            if resolved:
                resolved_imports.append(resolved)
            elif not imp.startswith('.'):
                resolved_imports.append(f'external:{imp}')

        return {
            'exports': exports,
            'imports': resolved_imports,
            'dependents': [],
            'category': self._categorize_file(rel_path),
            'language': language,
        }

    def build(self, ai_response: Optional[str] = None) -> Dict[str, Any]:
        """Build the dependency graph from scratch.

        Args:
            ai_response: Pre-fetched AI response for directory classification
                         (used when skill invokes this with AI access)
        """
        print(f'Scanning {self.project_dir}...')

        # Step 1: Classify directories (rules → AI → user)
        print('Classifying directories...')
        classifications = self._classify_directories(use_ai=True, ai_response=ai_response)
        source_count = sum(1 for d in classifications.get('directories', {}).values() if d.get('type') == 'source')
        exclude_count = sum(1 for d in classifications.get('directories', {}).values() if d.get('type') == 'exclude')
        print(f'Classified: {source_count} source dirs, {exclude_count} excluded dirs')

        # Step 2: Scan files using classifications
        files = self._scan_files(classifications)
        print(f'Found {len(files)} source files')

        # Build file info
        graph = {
            'version': 1,
            'commit': self._get_git_commit(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'project_root': str(self.project_dir),
            'files': {},
        }

        for file_path in files:
            rel_path = str(file_path.relative_to(self.project_dir))
            graph['files'][rel_path] = self._build_file_info(file_path)

        # Build dependents (reverse mapping)
        for file_path, info in graph['files'].items():
            for imp in info.get('imports', []):
                if not imp.startswith('external:') and imp in graph['files']:
                    graph['files'][imp]['dependents'].append(file_path)

        # Save graph
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        with open(self.graph_path, 'w') as f:
            json.dump(graph, f, indent=2)

        self.graph = graph

        # Summary
        total_imports = sum(len(f.get('imports', [])) for f in graph['files'].values())
        total_exports = sum(len(f.get('exports', [])) for f in graph['files'].values())

        return {
            'files_scanned': len(graph['files']),
            'total_imports': total_imports,
            'total_exports': total_exports,
            'commit': graph['commit'],
            'cached_to': str(self.graph_path),
        }

    def load(self) -> Optional[Dict[str, Any]]:
        """Load graph from cache."""
        if self.graph_path.exists():
            with open(self.graph_path) as f:
                self.graph = json.load(f)
            return self.graph
        return None

    def update(self) -> Dict[str, Any]:
        """Incrementally update the graph."""
        graph = self.load()
        if not graph:
            print('No cached graph found. Running full build...')
            return self.build()

        last_commit = graph.get('commit')
        if not last_commit:
            print('No commit info in cached graph. Running full build...')
            return self.build()

        changed_files = self._get_changed_files(last_commit)
        if not changed_files:
            return {'status': 'up_to_date', 'files_changed': 0}

        print(f'Updating graph for {len(changed_files)} changed files...')

        # Re-parse changed files
        for file_path in changed_files:
            full_path = self.project_dir / file_path
            if full_path.exists():
                # Check if it's a source file
                if self._detect_language(full_path):
                    graph['files'][file_path] = self._build_file_info(full_path)
            elif file_path in graph['files']:
                # File was deleted
                del graph['files'][file_path]

        # Rebuild dependents for affected files
        for file_path in graph['files']:
            graph['files'][file_path]['dependents'] = []

        for file_path, info in graph['files'].items():
            for imp in info.get('imports', []):
                if not imp.startswith('external:') and imp in graph['files']:
                    graph['files'][imp]['dependents'].append(file_path)

        # Update metadata
        graph['commit'] = self._get_git_commit()
        graph['timestamp'] = datetime.now(timezone.utc).isoformat()

        # Save
        with open(self.graph_path, 'w') as f:
            json.dump(graph, f, indent=2)

        self.graph = graph

        return {
            'status': 'updated',
            'files_changed': len(changed_files),
            'commit': graph['commit'],
        }

    def query(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Query dependency info for a file."""
        graph = self.load()
        if not graph:
            print('No cached graph found. Run /code-graph build first.')
            return None

        # Normalize path
        if file_path.startswith('./'):
            file_path = file_path[2:]

        info = graph['files'].get(file_path)
        if not info:
            print(f'File not found in graph: {file_path}')
            return None

        return {
            'file': file_path,
            'exports': info.get('exports', []),
            'imports': info.get('imports', []),
            'dependents': info.get('dependents', []),
            'category': info.get('category', 'unknown'),
            'language': info.get('language'),
        }

    def get_dependents(self, file_path: str, transitive: bool = True) -> Set[str]:
        """Get all files that depend on this file."""
        graph = self.load()
        if not graph:
            return set()

        if file_path.startswith('./'):
            file_path = file_path[2:]

        result = set()

        def traverse(path: str):
            info = graph['files'].get(path, {})
            for dep in info.get('dependents', []):
                if dep not in result:
                    result.add(dep)
                    if transitive:
                        traverse(dep)

        traverse(file_path)
        return result

    def get_dependencies(self, file_path: str, transitive: bool = True) -> Set[str]:
        """Get all files this file depends on."""
        graph = self.load()
        if not graph:
            return set()

        if file_path.startswith('./'):
            file_path = file_path[2:]

        result = set()

        def traverse(path: str):
            info = graph['files'].get(path, {})
            for imp in info.get('imports', []):
                if not imp.startswith('external:') and imp not in result:
                    result.add(imp)
                    if transitive:
                        traverse(imp)

        traverse(file_path)
        return result

    def get_impact(self, file_paths: List[str]) -> Dict[str, Set[str]]:
        """Get blast radius for multiple files."""
        graph = self.load()
        if not graph:
            return {}

        all_dependents = set()
        direct = set()

        for file_path in file_paths:
            if file_path.startswith('./'):
                file_path = file_path[2:]

            info = graph['files'].get(file_path)
            if info:
                direct.update(info.get('dependents', []))
                all_dependents.add(file_path)
                all_dependents.update(self.get_dependents(file_path, transitive=True))

        return {
            'input_files': set(file_paths),
            'direct_dependents': direct,
            'transitive_dependents': all_dependents - set(file_paths) - direct,
            'all_affected': all_dependents,
        }

    def clear(self) -> bool:
        """Clear the cached graph."""
        if self.graph_path.exists():
            self.graph_path.unlink()
            # Try to remove empty directory
            try:
                self.graph_dir.rmdir()
            except Exception:
                pass
            return True
        return False


def format_summary(data: Any, operation: str) -> str:
    """Format output as human-readable summary."""
    if operation == 'build':
        return f"""Built dependency graph:
  - {data['files_scanned']} files scanned
  - {data['total_imports']} import relationships
  - {data['total_exports']} export declarations
  - Cached to {data['cached_to']}"""

    elif operation == 'update':
        if data.get('status') == 'up_to_date':
            return "Graph is up to date. No changes detected."
        return f"""Updated dependency graph:
  - {data['files_changed']} files changed since last build
  - Graph updated at commit {data.get('commit', 'unknown')}"""

    elif operation == 'query':
        if not data:
            return "File not found in graph."

        lines = [f"File: {data['file']}", ""]

        if data.get('exports'):
            lines.append("Exports:")
            for exp in data['exports']:
                lines.append(f"  - {exp}")
            lines.append("")

        if data.get('imports'):
            lines.append("Dependencies (imports from):")
            for imp in data['imports']:
                prefix = "" if imp.startswith('external:') else "→ "
                lines.append(f"  - {imp} {prefix}")
            lines.append("")

        if data.get('dependents'):
            lines.append("Dependents (imported by):")
            for dep in data['dependents']:
                lines.append(f"  - {dep}")
            lines.append("")

        lines.append(f"Category: {data.get('category', 'unknown')}")
        return '\n'.join(lines)

    elif operation == 'impact':
        lines = [f"Impact analysis for: {', '.join(data['input_files'])}", ""]

        if data['direct_dependents']:
            lines.append(f"Direct impact ({len(data['direct_dependents'])} files):")
            for dep in sorted(data['direct_dependents']):
                lines.append(f"  - {dep}")
            lines.append("")

        if data['transitive_dependents']:
            lines.append(f"Transitive impact ({len(data['transitive_dependents'])} files):")
            for dep in sorted(data['transitive_dependents']):
                lines.append(f"  - {dep}")
            lines.append("")

        lines.append(f"Total blast radius: {len(data['all_affected'])} files affected")
        return '\n'.join(lines)

    elif operation == 'dependents':
        if not data:
            return "No cached graph found or file not in graph."

        lines = ["Dependents:"]
        for dep in sorted(data):
            lines.append(f"  - {dep}")
        return '\n'.join(lines)

    elif operation == 'dependencies':
        if not data:
            return "No cached graph found or file not in graph."

        lines = ["Dependencies:"]
        for dep in sorted(data):
            lines.append(f"  - {dep}")
        return '\n'.join(lines)

    elif operation == 'clear':
        return "Cleared dependency graph cache for this project."

    return str(data)


def main():
    parser = argparse.ArgumentParser(
        description='Code dependency graph operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build', action='store_true', help='Build graph from scratch')
    group.add_argument('--update', action='store_true', help='Update graph incrementally')
    group.add_argument('--query', metavar='FILE', help='Query file info')
    group.add_argument('--impact', nargs='+', metavar='FILE', help='Impact analysis')
    group.add_argument('--dependents', metavar='FILE', help='Get dependents')
    group.add_argument('--dependencies', metavar='FILE', help='Get dependencies')
    group.add_argument('--clear', action='store_true', help='Clear cache')

    parser.add_argument('--dir', metavar='PATH', help='Project directory')
    parser.add_argument('--format', choices=['json', 'summary'], default='json',
                       help='Output format (default: json)')

    args = parser.parse_args()

    graph = CodeGraph(args.dir)
    output = None
    operation = None

    if args.build:
        output = graph.build()
        operation = 'build'

    elif args.update:
        output = graph.update()
        operation = 'update'

    elif args.query:
        output = graph.query(args.query)
        operation = 'query'

    elif args.impact:
        output = graph.get_impact(args.impact)
        operation = 'impact'

    elif args.dependents:
        output = graph.get_dependents(args.dependents)
        operation = 'dependents'

    elif args.dependencies:
        output = graph.get_dependencies(args.dependencies)
        operation = 'dependencies'

    elif args.clear:
        output = graph.clear()
        operation = 'clear'

    if output is not None:
        if args.format == 'json':
            # Convert sets to lists for JSON serialization
            if isinstance(output, set):
                output = sorted(list(output))
            elif isinstance(output, dict):
                output = {k: sorted(list(v)) if isinstance(v, set) else v
                         for k, v in output.items()}
            print(json.dumps(output, indent=2))
        else:
            print(format_summary(output, operation))
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
