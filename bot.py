import os
import re
import asyncio
import shlex
import uuid
import docker
import discord
from discord import app_commands
from discord.ext import commands

TOKEN         = os.environ["DISCORD_TOKEN"]
GUILD_ID      = int(os.environ.get("GUILD_ID", "0")) or None
MAX_RAM_GB    = 40
MAX_CPU_CORES = 40
MAX_DISK_GB   = 400
NODE_IMAGE    = "vpsforge-node:latest"

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
dclient = docker.from_env()

TMATE_SSH_RE = re.compile(r"(ssh session:\s*ssh \S+@\S+)", re.IGNORECASE)
TMATE_WEB_RE = re.compile(r"(web session:\s*https?://\S+)", re.IGNORECASE)
SSHX_RE      = re.compile(r"(https?://sshx\.io/s/\S+)")


async def ensure_node_image():
    try:
        dclient.images.get(NODE_IMAGE)
    except docker.errors.ImageNotFound:
        dclient.images.build(
            path="/opt/vpsforge",
            dockerfile="vps_node.Dockerfile",
            tag=NODE_IMAGE,
            rm=True,
        )


def spawn_vps(ram_gb: int, cpu_cores: int, disk_gb: int, session: str):
    name = f"vps-{uuid.uuid4().hex[:8]}"
    # Note: disk quota depends on storage driver; we pass a size hint where supported.
    storage_opts = {}
    try:
        # Only overlay2/devicemapper honor size; vfs will ignore.
        storage_opts = {"size": f"{disk_gb}G"}
    except Exception:
        storage_opts = {}

    container = dclient.containers.run(
        NODE_IMAGE,
        name=name,
        detach=True,
        tty=True,
        stdin_open=True,
        mem_limit=f"{ram_gb}g",
        memswap_limit=f"{ram_gb}g",
        nano_cpus=cpu_cores * 1_000_000_000,
        storage_opt=storage_opts or None,
        cap_add=["NET_ADMIN", "SYS_PTRACE"],
        command="tail -f /dev/null",
    )
    return container, name


async def get_session_link(container, session: str) -> str:
    """Run tmate or sshx inside the container and scrape the connection URL."""
    if session == "tmate":
        cmd = (
            "bash -lc "
            + shlex.quote(
                "mkdir -p ~/.ssh && ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519 >/dev/null 2>&1; "
                "tmate -S /tmp/tmate.sock new-session -d && "
                "tmate -S /tmp/tmate.sock wait tmate-ready && "
                "echo \"ssh session: $(tmate -S /tmp/tmate.sock display -p '#{tmate_ssh}')\" && "
                "echo \"web session: $(tmate -S /tmp/tmate.sock display -p '#{tmate_web}')\""
            )
        )
    else:  # sshx
        cmd = "bash -lc 'sshx --quiet 2>&1 | tee /tmp/sshx.log & sleep 4; cat /tmp/sshx.log'"

    for _ in range(15):
        try:
            rc, out = container.exec_run(cmd, demux=False)
            text = out.decode(errors="ignore")
            if session == "tmate":
                ssh_m = TMATE_SSH_RE.search(text)
                web_m = TMATE_WEB_RE.search(text)
                if ssh_m:
                    lines = [ssh_m.group(1)]
                    if web_m:
                        lines.append(web_m.group(1))
                    return "\n".join(lines)
            else:
                m = SSHX_RE.search(text)
                if m:
                    return m.group(1)
        except Exception as e:
            print(f"[bot] exec error: {e}")
        await asyncio.sleep(2)
    return "Could not obtain session URL. Check container logs."


@bot.event
async def on_ready():
    await ensure_node_image()
    try:
        if GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        else:
            await bot.tree.sync()
    except Exception as e:
        print(f"[bot] sync failed: {e}")
    print(f"[bot] logged in as {bot.user}")


@bot.tree.command(name="deploy", description="Deploy a new VPS instance.")
@app_commands.describe(
    ram_gb="RAM in GB (max 40)",
    cpu_cores="CPU cores (max 40)",
    disk_gb="Disk in GB (max 400)",
    session="Remote session type",
    send_to="User to DM the credentials to",
)
@app_commands.choices(session=[
    app_commands.Choice(name="tmate", value="tmate"),
    app_commands.Choice(name="sshx",  value="sshx"),
])
async def deploy(
    interaction: discord.Interaction,
    ram_gb: int,
    cpu_cores: int,
    disk_gb: int,
    session: app_commands.Choice[str],
    send_to: discord.User,
):
    if not (1 <= ram_gb    <= MAX_RAM_GB):    return await interaction.response.send_message(f"RAM must be 1-{MAX_RAM_GB} GB.", ephemeral=True)
    if not (1 <= cpu_cores <= MAX_CPU_CORES): return await interaction.response.send_message(f"Cores must be 1-{MAX_CPU_CORES}.", ephemeral=True)
    if not (1 <= disk_gb   <= MAX_DISK_GB):   return await interaction.response.send_message(f"Disk must be 1-{MAX_DISK_GB} GB.", ephemeral=True)

    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        await ensure_node_image()
        container, name = await asyncio.to_thread(
            spawn_vps, ram_gb, cpu_cores, disk_gb, session.value
        )
    except Exception as e:
        return await interaction.followup.send(f"Spawn failed: `{e}`", ephemeral=True)

    link = await get_session_link(container, session.value)

    embed = discord.Embed(
        title="🖥️ Your VPS is ready",
        description=(
            f"**Container:** `{name}`\n"
            f"**RAM:** {ram_gb} GB · **CPU:** {cpu_cores} cores · **Disk:** {disk_gb} GB\n"
            f"**Session:** `{session.value}`\n\n"
            f"```\n{link}\n```\n"
            f"Default OS user: `vps` / password `vps` (sudo, passwordless)."
        ),
        color=0x2ecc71,
    )
    embed.set_footer(text="Use /destroy to tear it down.")

    try:
        await send_to.send(embed=embed)
        await interaction.followup.send(
            f"Delivered credentials to {send_to.mention} via DM. Container `{name}` is live.",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send(
            f"Couldn't DM {send_to.mention}. Here are the credentials instead:",
            embed=embed, ephemeral=True,
        )


@bot.tree.command(name="destroy", description="Destroy a VPS container by name.")
@app_commands.describe(name="Container name returned by /deploy")
async def destroy(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    try:
        c = dclient.containers.get(name)
        c.remove(force=True)
        await interaction.followup.send(f"Removed `{name}`.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: `{e}`", ephemeral=True)


@bot.tree.command(name="list", description="List active VPS containers.")
async def list_vps(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    conts = [c for c in dclient.containers.list() if c.name.startswith("vps-")]
    if not conts:
        return await interaction.followup.send("No active VPS containers.", ephemeral=True)
    body = "\n".join(f"`{c.name}` — {c.status}" for c in conts)
    await interaction.followup.send(f"**Active VPS containers:**\n{body}", ephemeral=True)


bot.run(TOKEN)
