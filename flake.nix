{
  description = "dinghy as a service";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, flake-utils, nixpkgs }: {
    nixosModule = { config, lib, pkgs, ... }:
      let
        cfg = config.services.dinghy-web;
      in
      with lib;
      {
        options.services.dinghy-web = {
          enable = mkEnableOption "Enables the dinghy-web service";

          githubToken = mkOption {
            type = types.either types.str types.path;
            description = mdDoc ''
              The GitHub token used to make requests against the GitHub API.
              Either a token or a path to a file containing the token.
            '';
          };

          projects = mkOption {
            type = types.listOf types.str;
            description = mdDoc ''
              The GitHub projects to watch.
            '';
            example = [ "Trundle/dinghy-web" ];
          };

          port = mkOption {
            type = types.port;
            default = 8080;
          };

          package = mkOption {
            type = types.package;
            description = lib.mdDoc ''
              Which dinghy-web derivation to use.
            '';
            default = self.defaultPackage.${pkgs.system};
          };
        };

        config = mkIf cfg.enable {
          systemd.services.dinghy-web = {
            description = "dinghy as a service";

            wantedBy = [ "multi-user.target" ];
            wants = [ "network-online.target" ];
            after = [ "network.target" ];

            environment = {
              PORT = toString cfg.port;
              PROJECTS = strings.concatStringsSep " " cfg.projects;
            } // (
              if (strings.hasPrefix "ghp_" cfg.githubToken)
              then { GITHUB_TOKEN = cfg.githubToken; }
              else { GITHUB_TOKEN_FILE = cfg.githubToken; }
            );

            serviceConfig = {
              ExecStart = "${cfg.package}/bin/dinghy-web";
              DynamicUser = true;
            };
          };
        };
      };
  } // flake-utils.lib.eachDefaultSystem (system:
    let
      pkgs = import nixpkgs {
        inherit system;
      };
    in
    {
      defaultPackage = pkgs.python3Packages.callPackage ./default.nix { };
    });
}
