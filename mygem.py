#!/usr/bin/env python3
"""
Enhanced Gemini CLI - A feature-rich command-line interface for Google's Gemini API
Supports streaming, multi-turn conversations, markdown formatting, and more.
"""

import os
import sys
import argparse
import requests
import json
import time
import textwrap
import re
from typing import List, Dict, Optional, Iterator

# ANSI color codes for terminal formatting
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'

class MarkdownFormatter:
    """Simple markdown formatter for terminal output."""
    
    @staticmethod
    def format_text(text: str, use_colors: bool = True) -> str:
        """Format markdown-style text for terminal display."""
        if not use_colors:
            # Strip markdown formatting for plain text
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Bold
            text = re.sub(r'\*(.*?)\*', r'\1', text)      # Italic
            text = re.sub(r'`([^`]+)`', r'\1', text)      # Inline code
            return text
        
        # Apply terminal colors for markdown
        text = re.sub(r'\*\*(.*?)\*\*', f'{Colors.BOLD}\\1{Colors.RESET}', text)  # Bold
        text = re.sub(r'\*(.*?)\*', f'{Colors.DIM}\\1{Colors.RESET}', text)       # Italic
        text = re.sub(r'`([^`]+)`', f'{Colors.CYAN}\\1{Colors.RESET}', text)      # Inline code
        
        # Handle code blocks
        lines = text.split('\n')
        formatted_lines = []
        in_code_block = False
        
        for line in lines:
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                if in_code_block:
                    formatted_lines.append(f'{Colors.GRAY}┌─ Code Block ─{Colors.RESET}')
                else:
                    formatted_lines.append(f'{Colors.GRAY}└──────────────{Colors.RESET}')
            elif in_code_block:
                formatted_lines.append(f'{Colors.GRAY}│{Colors.RESET} {Colors.GREEN}{line}{Colors.RESET}')
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)

class ConversationManager:
    """Manages multi-turn conversation context."""
    
    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.system_prompt: Optional[str] = None
    
    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.history.append({"role": role, "parts": [{"text": content}]})
    
    def get_context(self) -> List[Dict]:
        """Get the full conversation context for API requests."""
        return self.history
    
    def clear(self):
        """Clear conversation history."""
        self.history.clear()
    
    def set_system_prompt(self, prompt: str):
        """Set a system prompt for the conversation."""
        self.system_prompt = prompt

class GeminiAPI:
    """Enhanced Gemini API client with streaming support."""
    
    def __init__(self, api_key: str, debug: bool = False):
        self.api_key = api_key
        self.debug = debug
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
    
    def _debug_print(self, message: str):
        """Print debug information if debug mode is enabled."""
        if self.debug:
            print(f"{Colors.YELLOW}[DEBUG]{Colors.RESET} {message}", file=sys.stderr)
    
    def generate_streaming(
        self,
        model: str,
        conversation: ConversationManager,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        retries: int = 3
    ) -> Iterator[str]:
        """Generate streaming response from Gemini API."""
        
        url = f"{self.base_url}/{model}:streamGenerateContent?key={self.api_key}&alt=sse"
        headers = {"Content-Type": "application/json"}
        
        # Prepare the request body
        body = {
            "contents": conversation.get_context(),
            "generationConfig": {
                "temperature": temperature,
            }
        }
        
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        
        if conversation.system_prompt:
            body["systemInstruction"] = {"parts": [{"text": conversation.system_prompt}]}
        
        self._debug_print(f"Sending request to: {url}")
        self._debug_print(f"Request body: {json.dumps(body, indent=2)}")
        
        for attempt in range(retries):
            try:
                response = requests.post(
                    url, 
                    headers=headers, 
                    json=body, 
                    timeout=120,
                    stream=True
                )
                response.raise_for_status()
                
                accumulated_text = ""
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith('data: '):
                        continue
                    
                    json_str = line[6:]  # Remove 'data: ' prefix
                    if json_str.strip() == '[DONE]':
                        break
                    
                    try:
                        data = json.loads(json_str)
                        if 'candidates' in data and data['candidates']:
                            candidate = data['candidates'][0]
                            if 'content' in candidate and 'parts' in candidate['content']:
                                text_part = candidate['content']['parts'][0].get('text', '')
                                if text_part:
                                    accumulated_text += text_part
                                    yield text_part
                    except json.JSONDecodeError:
                        continue
                
                # Add the complete response to conversation history
                if accumulated_text:
                    conversation.add_message("model", accumulated_text)
                
                return
                
            except requests.HTTPError as e:
                if e.response.status_code == 503 and attempt < retries - 1:
                    wait_time = 2 ** attempt
                    self._debug_print(f"503 error, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise
            except requests.RequestException as e:
                if attempt < retries - 1:
                    wait_time = 2 ** attempt
                    self._debug_print(f"Request failed, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise
        
        raise RuntimeError(f"Failed after {retries} retries")
    
    def generate_simple(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        retries: int = 3
    ) -> str:
        """Generate a simple, non-streaming response."""
        
        url = f"{self.base_url}/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
            }
        }
        
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        
        self._debug_print(f"Sending simple request to: {url}")
        self._debug_print(f"Request body: {json.dumps(body, indent=2)}")
        
        for attempt in range(retries):
            try:
                response = requests.post(url, headers=headers, json=body, timeout=120)
                response.raise_for_status()
                data = response.json()
                
                self._debug_print(f"Response: {json.dumps(data, indent=2)}")
                
                if 'candidates' in data and data['candidates']:
                    return data['candidates'][0]['content']['parts'][0]['text'].strip()
                else:
                    return "No response generated."
                    
            except requests.HTTPError as e:
                if e.response.status_code == 503 and attempt < retries - 1:
                    wait_time = 2 ** attempt
                    self._debug_print(f"503 error, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise
            except (KeyError, IndexError):
                return json.dumps(data, indent=2)
        
        raise RuntimeError(f"Failed after {retries} retries")

class CLI:
    """Main CLI interface."""
    
    def __init__(self):
        self.conversation = ConversationManager()
        self.api = None
        self.formatter = MarkdownFormatter()
        self.use_colors = self._supports_color()
    
    def _supports_color(self) -> bool:
        """Check if terminal supports colors."""
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    
    def _print_header(self):
        """Print a nice header for the CLI."""
        if self.use_colors:
            print(f"\n{Colors.CYAN}╔══════════════════════════════════════╗{Colors.RESET}")
            print(f"{Colors.CYAN}║{Colors.RESET}     {Colors.BOLD}Enhanced Gemini CLI{Colors.RESET}           {Colors.CYAN}║{Colors.RESET}")
            print(f"{Colors.CYAN}╚══════════════════════════════════════╝{Colors.RESET}\n")
        else:
            print("\n" + "="*40)
            print("     Enhanced Gemini CLI")
            print("="*40 + "\n")
    
    def _print_prompt(self):
        """Print the user input prompt."""
        if self.use_colors:
            print(f"\n{Colors.BLUE}You:{Colors.RESET} ", end="", flush=True)
        else:
            print("\nYou: ", end="", flush=True)
    
    def _print_assistant_header(self):
        """Print the assistant response header."""
        if self.use_colors:
            print(f"\n{Colors.MAGENTA}Assistant:{Colors.RESET}")
        else:
            print("\nAssistant:")
    
    def _read_input(self) -> str:
        """Read from stdin if available."""
        if not sys.stdin.isatty():
            return sys.stdin.read().strip()
        return ""
    
    def _read_file(self, filepath: str) -> str:
        """Read content from a file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"{Colors.RED}Error:{Colors.RESET} File '{filepath}' not found.", file=sys.stderr)
            sys.exit(1)
        except IOError as e:
            print(f"{Colors.RED}Error:{Colors.RESET} Could not read file '{filepath}': {e}", file=sys.stderr)
            sys.exit(1)
    
    def interactive_mode(self, args):
        """Run in interactive chat mode."""
        self._print_header()
        
        if self.use_colors:
            print(f"{Colors.GREEN}Interactive mode started.{Colors.RESET}")
            print(f"{Colors.GRAY}Type 'exit', 'quit', or Ctrl+C to end the session.{Colors.RESET}")
            print(f"{Colors.GRAY}Use '/clear' to reset conversation history.{Colors.RESET}")
            print(f"{Colors.GRAY}Model: {Colors.CYAN}{args.model}{Colors.RESET}")
        else:
            print("Interactive mode started.")
            print("Type 'exit', 'quit', or Ctrl+C to end the session.")
            print("Use '/clear' to reset conversation history.")
            print(f"Model: {args.model}")
        
        try:
            while True:
                self._print_prompt()
                try:
                    user_input = input().strip()
                except EOFError:
                    print(f"\n{Colors.GRAY}Goodbye!{Colors.RESET}")
                    break
                
                if user_input.lower() in ['exit', 'quit']:
                    print(f"{Colors.GRAY}Goodbye!{Colors.RESET}")
                    break
                
                if user_input == '/clear':
                    self.conversation.clear()
                    if self.use_colors:
                        print(f"{Colors.YELLOW}Conversation history cleared.{Colors.RESET}")
                    else:
                        print("Conversation history cleared.")
                    continue
                
                if not user_input:
                    continue
                
                # Add user message to conversation
                self.conversation.add_message("user", user_input)
                
                self._print_assistant_header()
                
                try:
                    response_text = ""
                    for chunk in self.api.generate_streaming(
                        model=args.model,
                        conversation=self.conversation,
                        temperature=args.temperature,
                        max_tokens=args.max_tokens,
                        retries=args.retries
                    ):
                        formatted_chunk = self.formatter.format_text(chunk, self.use_colors)
                        print(formatted_chunk, end="", flush=True)
                        response_text += chunk
                    
                    print()  # New line after response
                    
                except Exception as e:
                    print(f"{Colors.RED}Error:{Colors.RESET} {e}", file=sys.stderr)
        
        except KeyboardInterrupt:
            print(f"\n{Colors.GRAY}Goodbye!{Colors.RESET}")
    
    def single_prompt_mode(self, args):
        """Handle single prompt and exit."""
        # Gather input from various sources
        stdin_input = self._read_input()
        file_input = self._read_file(args.file) if args.file else ""
        prompt_input = args.prompt or ""
        
        # Combine inputs
        full_prompt = []
        if prompt_input:
            full_prompt.append(prompt_input)
        if file_input:
            full_prompt.append(file_input)
        if stdin_input:
            full_prompt.append(stdin_input)
        
        if not full_prompt:
            print(f"{Colors.RED}Error:{Colors.RESET} No prompt provided. Use -p, -f, or pipe input.", file=sys.stderr)
            sys.exit(1)
        
        final_prompt = "\n\n".join(full_prompt)
        
        if args.style:
            final_prompt = f"[Style: {args.style}]\n{final_prompt}"
        
        try:
            if args.stream:
                # Use streaming even for single prompts if requested
                self.conversation.add_message("user", final_prompt)
                
                for chunk in self.api.generate_streaming(
                    model=args.model,
                    conversation=self.conversation,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    retries=args.retries
                ):
                    formatted_chunk = self.formatter.format_text(chunk, self.use_colors)
                    print(formatted_chunk, end="", flush=True)
                print()  # New line at end
            else:
                # Use simple generation for faster single responses
                response = self.api.generate_simple(
                    model=args.model,
                    prompt=final_prompt,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    retries=args.retries
                )
                formatted_response = self.formatter.format_text(response, self.use_colors)
                print(formatted_response)
        
        except requests.HTTPError as e:
            error_msg = f"HTTP error: {e.response.status_code}"
            if hasattr(e.response, 'text'):
                error_msg += f" {e.response.text}"
            print(f"{Colors.RED}Error:{Colors.RESET} {error_msg}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"{Colors.RED}Error:{Colors.RESET} {e}", file=sys.stderr)
            sys.exit(2)
    
    def run(self):
        """Main entry point."""
        parser = argparse.ArgumentParser(
            description="Enhanced Gemini CLI - Interactive AI chat with streaming and multi-turn support",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=textwrap.dedent("""
            Examples:
              %(prog)s                                    # Start interactive mode
              %(prog)s -p "Explain quantum computing"    # Single prompt
              cat file.py | %(prog)s -p "Review this code"
              %(prog)s -f document.txt -p "Summarize this"
              %(prog)s -i -m gemini-2.0-flash-exp       # Interactive with specific model
            """)
        )
        
        parser.add_argument("-p", "--prompt", help="Prompt text to send")
        parser.add_argument("-f", "--file", help="Read additional input from file")
        parser.add_argument("-i", "--interactive", action="store_true", 
                          help="Start interactive chat mode")
        parser.add_argument("-m", "--model", 
                          default=os.getenv("MYGEM_MODEL", "gemini-2.0-flash-exp"),
                          help="Model name (default: gemini-2.0-flash-exp)")
        parser.add_argument("-s", "--style", 
                          help="Response style: creative, concise, technical, etc.")
        parser.add_argument("-t", "--temperature", type=float, default=0.3,
                          help="Temperature (randomness) 0.0-1.0 (default: 0.3)")
        parser.add_argument("-x", "--max-tokens", type=int,
                          help="Maximum output tokens")
        parser.add_argument("-r", "--retries", type=int, default=3,
                          help="Number of retries on errors (default: 3)")
        parser.add_argument("--stream", action="store_true",
                          help="Use streaming output even for single prompts")
        parser.add_argument("--no-color", action="store_true",
                          help="Disable colored output")
        parser.add_argument("--debug", action="store_true",
                          help="Enable debug output")
        parser.add_argument("--docs", action="store_true",
                          help="Show extended documentation")
        
        args = parser.parse_args()
        
        if args.docs:
            self._show_docs()
            sys.exit(0)
        
        if args.no_color:
            self.use_colors = False
        
        # Validate temperature
        if not 0.0 <= args.temperature <= 1.0:
            print(f"{Colors.RED}Error:{Colors.RESET} Temperature must be between 0.0 and 1.0", file=sys.stderr)
            sys.exit(1)
        
        # Initialize API client
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print(f"{Colors.RED}Error:{Colors.RESET} GEMINI_API_KEY environment variable not set", file=sys.stderr)
            print("Please set your API key: export GEMINI_API_KEY='your-api-key-here'", file=sys.stderr)
            sys.exit(1)
        
        self.api = GeminiAPI(api_key, debug=args.debug)
        
        # Determine mode
        has_input = args.prompt or args.file or not sys.stdin.isatty()
        
        if args.interactive or not has_input:
            self.interactive_mode(args)
        else:
            self.single_prompt_mode(args)
    
    def _show_docs(self):
        """Show extended documentation."""
        docs = f"""
{Colors.BOLD if self.use_colors else ''}Enhanced Gemini CLI - Advanced Command Line Interface{Colors.RESET if self.use_colors else ''}
{'='*70}

{Colors.CYAN if self.use_colors else ''}FEATURES:{Colors.RESET if self.use_colors else ''}
  • Streaming responses with real-time output
  • Multi-turn conversations with memory
  • Markdown formatting with syntax highlighting
  • Interactive chat mode
  • Flexible input methods (prompt, file, stdin)
  • Colored terminal output
  • Robust error handling with retries

{Colors.CYAN if self.use_colors else ''}USAGE:{Colors.RESET if self.use_colors else ''}
  {Colors.GREEN if self.use_colors else ''}gemini-cli{Colors.RESET if self.use_colors else ''}                                    # Interactive mode
  {Colors.GREEN if self.use_colors else ''}gemini-cli{Colors.RESET if self.use_colors else ''} -p "prompt text" [options]       # Single prompt
  {Colors.GREEN if self.use_colors else ''}cat file.txt | gemini-cli{Colors.RESET if self.use_colors else ''} -p "prompt text"  # Pipe input
  {Colors.GREEN if self.use_colors else ''}gemini-cli{Colors.RESET if self.use_colors else ''} -f file.txt -p "Explain this"    # File input

{Colors.CYAN if self.use_colors else ''}OPTIONS:{Colors.RESET if self.use_colors else ''}
  -h, --help          Show help message
  --docs              Show this documentation
  -p, --prompt        Prompt text to send to Gemini
  -f, --file          Read additional input from file
  -i, --interactive   Start interactive chat mode
  -m, --model         Model name (default: gemini-2.0-flash-exp)
  -s, --style         Response style: creative, concise, technical, etc.
  -t, --temperature   Sampling temperature (0.0-1.0, default 0.3)
  -x, --max-tokens    Maximum output tokens
  -r, --retries       Number of retries on errors (default 3)
  --stream            Use streaming output for single prompts
  --no-color          Disable colored output
  --debug             Enable debug output

{Colors.CYAN if self.use_colors else ''}POPULAR MODELS:{Colors.RESET if self.use_colors else ''}
  gemini-2.0-flash-exp    - Latest experimental model (default)
  gemini-1.5-pro          - High-quality, reasoning tasks
  gemini-1.5-flash        - Fast, efficient responses

{Colors.CYAN if self.use_colors else ''}INTERACTIVE COMMANDS:{Colors.RESET if self.use_colors else ''}
  /clear              Clear conversation history
  exit, quit          Exit interactive mode
  Ctrl+C              Force exit

{Colors.CYAN if self.use_colors else ''}ENVIRONMENT VARIABLES:{Colors.RESET if self.use_colors else ''}
  GEMINI_API_KEY      Your Gemini API key (required)
  MYGEM_MODEL         Default model to use

{Colors.CYAN if self.use_colors else ''}EXAMPLES:{Colors.RESET if self.use_colors else ''}
  # Start interactive chat
  {Colors.GRAY if self.use_colors else ''}gemini-cli -i{Colors.RESET if self.use_colors else ''}

  # Single prompt with specific model
  {Colors.GRAY if self.use_colors else ''}gemini-cli -p "Explain machine learning" -m gemini-1.5-pro{Colors.RESET if self.use_colors else ''}

  # Analyze code file with streaming
  {Colors.GRAY if self.use_colors else ''}gemini-cli -f script.py -p "Review this code" --stream{Colors.RESET if self.use_colors else ''}

  # Creative writing with high temperature
  {Colors.GRAY if self.use_colors else ''}gemini-cli -p "Write a story about space" -s creative -t 0.9{Colors.RESET if self.use_colors else ''}

  # Process stdin input
  {Colors.GRAY if self.use_colors else ''}echo "Hello world" | gemini-cli -p "Translate to Spanish"{Colors.RESET if self.use_colors else ''}

{Colors.CYAN if self.use_colors else ''}TIPS:{Colors.RESET if self.use_colors else ''}
  • Use low temperature (0.1-0.3) for factual, consistent responses
  • Use high temperature (0.7-0.9) for creative, varied outputs
  • Interactive mode maintains conversation context automatically
  • Combine -f and -p to provide context and specific instructions
  • Use --debug to troubleshoot API issues
  • The tool auto-detects terminal color support
        """
        print(textwrap.dedent(docs))

def main():
    """Entry point for the CLI."""
    cli = CLI()
    cli.run()

if __name__ == "__main__":
    main()
