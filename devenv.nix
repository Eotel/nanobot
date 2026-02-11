{ pkgs, ... }:

{
  languages.python = {
    enable = true;
    version = "3.12";
    uv = {
      enable = true;
      sync.enable = true;
    };
  };

  packages = [
    pkgs.ruff
    pkgs.ty
    pkgs.treefmt
    pkgs.nixfmt
  ];

  git-hooks.hooks = {
    ruff.enable = true;
    ruff-format.enable = true;
    treefmt.enable = true;
  };

  enterShell = ''
    echo "nanobot dev environment"
    echo "  python: $(python --version)"
    echo "  uv:     $(uv --version)"
    echo "  ruff:   $(ruff --version)"
    echo "  ty:     $(ty --version)"
  '';
}
