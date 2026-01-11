import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle
import asyncio
import uuid
import os
from dotenv import load_dotenv

# ===================== ЗАГРУЗКА ТОКЕНА ИЗ .env =====================
load_dotenv()  # Загружаем переменные из .env файла

# Чтение токена из .env
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("❌ ОШИБКА: DISCORD_TOKEN не найден в .env файле!")
    print("Создайте файл .env в той же папке и добавьте:")
    print("DISCORD_TOKEN=ваш_токен_здесь")
    exit(1)

# ===================== НАСТРОЙКИ =====================
# ID ролей и каналов (остаются в коде)
HIGH_ROLES = [1174860973522288780, 1089620679021842605, 1174878142259793962, 1245089436723581042]  # Роли админов
TIER_ROLES = {
    1: 1458095828722909224,  # Тир 1
    2: 1458095871810867250,  # Тир 2
    3: 1458095875460173938   # Тир 3
}
ALLOWED_CHANNEL = 1451552947300204594  # Канал для команд

# Хранилище данных
active_vzp = {}
closed_vzp = {}
swap_history = {}  # {vzp_id: {old_user_id: new_user_id}}

# ===================== НАСТРОЙКА БОТА =====================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
intents.voice_states = True

class VZPBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
    
    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            print(f"✅ Синхронизировано {len(synced)} команд")
        except Exception as e:
            print(f"❌ Ошибка синхронизации: {e}")

bot = VZPBot()

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
async def is_allowed_channel(interaction: discord.Interaction) -> bool:
    return interaction.channel_id == ALLOWED_CHANNEL

async def has_high_role(interaction: discord.Interaction) -> bool:
    return any(role.id in HIGH_ROLES for role in interaction.user.roles)

async def update_vzp_message(vzp_id: str):
    if vzp_id not in active_vzp:
        return
    
    data = active_vzp[vzp_id]
    channel = bot.get_channel(data['channel_id'])
    if not channel:
        return
    
    try:
        message = await channel.fetch_message(data['message_id'])
    except:
        return
    
    # Сортируем по тирам
    tier_lists = {1: [], 2: [], 3: []}
    
    for user_id, tier in data['plus_users'].items():
        tier_lists[tier].append(user_id)
    
    # Получаем историю замен для этой VZP
    vzp_swaps = swap_history.get(vzp_id, {})
    
    # Определяем статус и цвет
    status = data.get('status', 'OPEN')
    if status == 'OPEN':
        color = discord.Color.green()
        status_text = "OPEN"
    elif status == 'LIST IN PROCESS':
        color = discord.Color.gold()
        status_text = "LIST IN PROCESS"
    elif status == 'VZP IN PROCESS':
        color = discord.Color.blue()
        status_text = "VZP IN PROCESS"
    elif status == 'CLOSED':
        color = discord.Color.red()
        status_text = "CLOSED"
    else:
        color = discord.Color.green()
        status_text = status
    
    # Формируем описание в правильном формате
    attack_def_display = data.get('attack_def_name', 'АТАКА').split(' ')[1]
    conditions_display = data.get('conditions_display', ['Условие'])
    caliber_names = data.get('caliber_names', ['5.56 mm', '7.62 mm', '9 mm'])
    
    description = f"**{attack_def_display} vs {data['enemy']} {len(data['plus_users'])}/{data['members']} {data['time']}**\n"
    description += f"\n**{', '.join(conditions_display)}**\n"
    description += f"**{caliber_names[0]} + {caliber_names[1]} + {caliber_names[2]}**"
    
    # Создаём embed
    embed = discord.Embed(
        description=description,
        color=color
    )
    
    # Добавляем тиры
    for tier_num in [1, 2, 3]:
        members_list = []
        for user_id in tier_lists[tier_num]:
            member = channel.guild.get_member(user_id)
            if member:
                members_list.append(f"• {member.mention}")
        
        tier_name = {1: "TIER 1", 2: "TIER 2", 3: "TIER 3"}[tier_num]
        
        if members_list:
            embed.add_field(
                name=f"**{tier_name}** ({len(tier_lists[tier_num])})",
                value="\n".join(members_list),
                inline=False
            )
        else:
            embed.add_field(
                name=f"**{tier_name}** (0)",
                value="—",
                inline=False
            )
    
    # Добавляем секцию SWAP если есть замены
    if vzp_swaps:
        swap_list = []
        for old_user_id, new_user_id in vzp_swaps.items():
            old_member = channel.guild.get_member(old_user_id)
            new_member = channel.guild.get_member(new_user_id)
            if old_member and new_member:
                swap_list.append(f"• {new_member.mention} → {old_member.mention}")
        
        if swap_list:
            embed.add_field(
                name="**SWAP**",
                value="\n".join(swap_list),
                inline=False
            )
    
    # Статус и ID
    embed.add_field(
        name="**STATUS**",
        value=f"```{status_text}```",
        inline=False
    )
    
    embed.add_field(
        name="**ID**",
        value=f"```{vzp_id}```",
        inline=False
    )
    
    # Кнопка только если статус OPEN
    view = ui.View()
    if status == 'OPEN':
        button = ui.Button(
            style=ButtonStyle.green,
            label="ПОДАТЬ ПЛЮС",
            custom_id=f"vzp_plus_{vzp_id}"
        )
        
        async def plus_callback(interaction_btn: discord.Interaction):
            user_tier = None
            for tier_num, role_id in TIER_ROLES.items():
                if any(role.id == role_id for role in interaction_btn.user.roles):
                    user_tier = tier_num
                    break
            
            if not user_tier:
                await interaction_btn.response.send_message(
                    "❌ У вас нет необходимой роли для участия в VZP!",
                    ephemeral=True
                )
                return
            
            if data['status'] != 'OPEN':
                await interaction_btn.response.send_message(
                    f"❌ Набор на эту VZP закрыт! Текущий статус: {data['status']}",
                    ephemeral=True
                )
                return
            
            # Проверяем не является ли пользователь заменой
            vzp_swaps_current = swap_history.get(vzp_id, {})
            if interaction_btn.user.id in vzp_swaps_current.values():
                await interaction_btn.response.send_message(
                    "❌ Вы уже в списке замен!",
                    ephemeral=True
                )
                return
            
            if interaction_btn.user.id in data['plus_users']:
                await interaction_btn.response.send_message(
                    "❌ Вы уже подали заявку на эту VZP!",
                    ephemeral=True
                )
                return
            
            # Добавляем участника
            data['plus_users'][interaction_btn.user.id] = user_tier
            await update_vzp_message(vzp_id)
            
            try:
                notify_embed = discord.Embed(
                    title="✅ ВЫ УСПЕШНО ЗАПИСАЛИСЬ НА VZP!",
                    color=discord.Color.green()
                )
                notify_embed.add_field(name="ID VZP", value=vzp_id, inline=False)
                notify_embed.add_field(name="Тип", value=attack_def_display, inline=True)
                notify_embed.add_field(name="Противник", value=data['enemy'], inline=True)
                notify_embed.add_field(name="Условия", value=", ".join(conditions_display), inline=False)
                notify_embed.add_field(name="Калибры", value=f"{caliber_names[0]} + {caliber_names[1]} + {caliber_names[2]}", inline=False)
                notify_embed.add_field(name="Время", value=data['time'], inline=True)
                notify_embed.add_field(name="Ваш тир", value=f"Tier {user_tier}", inline=True)
                notify_embed.set_footer(text="Ожидайте начала VZP")
                
                await interaction_btn.user.send(embed=notify_embed)
            except:
                pass
            
            await interaction_btn.response.send_message(
                f"✅ Вы успешно записались на VZP! Проверьте ЛС.",
                ephemeral=True
            )
        
        button.callback = plus_callback
        view.add_item(button)
    
    await message.edit(embed=embed, view=view)

async def notify_users_ls(vzp_id: str, title: str, message: str, guild: discord.Guild, user_ids=None):
    if vzp_id not in active_vzp:
        return 0
    
    data = active_vzp[vzp_id]
    notified = 0
    
    if user_ids:
        target_ids = user_ids
    else:
        target_ids = data['plus_users'].keys()
    
    for user_id in target_ids:
        member = guild.get_member(user_id)
        if member:
            try:
                embed = discord.Embed(
                    title=title,
                    description=message,
                    color=discord.Color.blue()
                )
                embed.add_field(name="VZP ID", value=vzp_id, inline=False)
                embed.add_field(name="Время", value=data['time'], inline=True)
                embed.add_field(name="Противник", value=data['enemy'], inline=True)
                embed.set_footer(text="VZP Manager")
                
                await member.send(embed=embed)
                notified += 1
            except Exception as e:
                print(f"❌ Не удалось отправить уведомление {member.name}: {e}")
            
            await asyncio.sleep(1)
    
    return notified

# ===================== ВСЕ СЛЕШ-КОМАНДЫ =====================

@bot.tree.command(name="vzp_start", description="Создать новую VZP с выбором условий")
@app_commands.describe(
    time="Время VZP (например: 20:00)",
    members="Количество участников",
    enemy="Имя противника",
    attack_def="Выберите АТАКУ или ОБОРОНУ",
    condition1="Выберите первое условие забива (обязательно)",
    caliber1="Выберите первый калибр",
    caliber2="Выберите второй калибр",
    caliber3="Выберите третий калибр",
    condition2="Выберите второе условие забива (не обязательно)",
    condition3="Выберите третье условие забива (не обязательно)"
)
@app_commands.choices(
    attack_def=[
        app_commands.Choice(name=" АТАКА", value="ATT"),
        app_commands.Choice(name=" ДЕФ", value="DEF")
    ],
    condition1=[
        app_commands.Choice(name=" Алкоголь/анальгетик", value="alcohol"),
        app_commands.Choice(name=" Косяки/SPANK", value="joints"),
        app_commands.Choice(name=" Аптечки", value="medkits"),
        app_commands.Choice(name=" Броня", value="armor")
    ],
    condition2=[
        app_commands.Choice(name=" Алкоголь/анальгетик", value="alcohol"),
        app_commands.Choice(name=" Косяки/SPANK", value="joints"),
        app_commands.Choice(name=" Аптечки", value="medkits"),
        app_commands.Choice(name=" Броня", value="armor"),
    ],
    condition3=[
        app_commands.Choice(name=" Алкоголь/анальгетик", value="alcohol"),
        app_commands.Choice(name=" Косяки/SPANK", value="joints"),
        app_commands.Choice(name=" Аптечки", value="medkits"),
        app_commands.Choice(name=" Броня", value="armor"),
    ],
    caliber1=[
        app_commands.Choice(name="5.56 mm", value="5.56"),
        app_commands.Choice(name="7.62 mm", value="7.62"),
        app_commands.Choice(name="11.43 mm", value="11.43"),
        app_commands.Choice(name="9 mm", value="9"),
        app_commands.Choice(name="12 mm", value="12")
    ],
    caliber2=[
        app_commands.Choice(name="5.56 mm", value="5.56"),
        app_commands.Choice(name="7.62 mm", value="7.62"),
        app_commands.Choice(name="11.43 mm", value="11.43"),
        app_commands.Choice(name="9 mm", value="9"),
        app_commands.Choice(name="12 mm", value="12")
    ],
    caliber3=[
        app_commands.Choice(name="5.56 mm", value="5.56"),
        app_commands.Choice(name="7.62 mm", value="7.62"),
        app_commands.Choice(name="11.43 mm", value="11.43"),
        app_commands.Choice(name="9 mm", value="9"),
        app_commands.Choice(name="12 mm", value="12")
    ]
)
async def vzp_start(
    interaction: discord.Interaction, 
    time: str, 
    members: int, 
    enemy: str,
    attack_def: app_commands.Choice[str],
    condition1: app_commands.Choice[str],
    caliber1: app_commands.Choice[str],
    caliber2: app_commands.Choice[str],
    caliber3: app_commands.Choice[str],
    condition2: app_commands.Choice[str] = None,
    condition3: app_commands.Choice[str] = None
):
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для создания VZP!",
            ephemeral=True
        )
        return
    
    vzp_id = str(uuid.uuid4())[:8]
    
    # Преобразуем названия условий в читаемый формат
    condition_names = {
        "alcohol": "Алкоголь/анальгетик",
        "joints": "Косяки/SPANK",
        "medkits": "Аптечки",
        "armor": "Броня"
    }
    
    # Собираем все выбранные условия (исключая дубликаты)
    selected_conditions = []
    conditions_display = []
    conditions_values = []
    
    # Первое условие обязательно
    selected_conditions.append(condition1.value)
    conditions_display.append(condition_names.get(condition1.value, condition1.value))
    conditions_values.append(condition1.value)
    
    # Второе условие (если выбрано и не дубликат)
    if condition2 and condition2.value not in selected_conditions:
        selected_conditions.append(condition2.value)
        conditions_display.append(condition_names.get(condition2.value, condition2.value))
        conditions_values.append(condition2.value)
    
    # Третье условие (если выбрано и не дубликат)
    if condition3 and condition3.value not in selected_conditions:
        selected_conditions.append(condition3.value)
        conditions_display.append(condition_names.get(condition3.value, condition3.value))
        conditions_values.append(condition3.value)
    
    # Проверяем что калибры разные
    calibers = [caliber1.value, caliber2.value, caliber3.value]
    if len(set(calibers)) < 3:
        await interaction.response.send_message(
            "❌ Выберите три РАЗНЫХ калибра!",
            ephemeral=True
        )
        return
    
    # Формируем описание в правильном формате
    description = f"**{attack_def.name.split(' ')[1]} vs {enemy} 0/{members} {time}**\n"
    description += f"\n**{', '.join(conditions_display)}**\n"
    description += f"**{caliber1.name} + {caliber2.name} + {caliber3.name}**"
    
    embed = discord.Embed(
        description=description,
        color=discord.Color.green()
    )
    
    # Добавляем тиры
    for tier_num in [1, 2, 3]:
        embed.add_field(
            name=f"**TIER {tier_num}** (0)",
            value="—",
            inline=False
        )
    
    embed.add_field(
        name="**STATUS**",
        value=f"```OPEN```",
        inline=False
    )
    
    embed.add_field(
        name="**ID**",
        value=f"```{vzp_id}```",
        inline=False
    )
    
    view = ui.View()
    button = ui.Button(
        style=ButtonStyle.green,
        label="ПОДАТЬ ПЛЮС",
        custom_id=f"vzp_plus_{vzp_id}"
    )
    
    async def plus_callback(interaction_btn: discord.Interaction):
        user_tier = None
        for tier_num, role_id in TIER_ROLES.items():
            if any(role.id == role_id for role in interaction_btn.user.roles):
                user_tier = tier_num
                break
        
        if not user_tier:
            await interaction_btn.response.send_message(
                "❌ У вас нет необходимой роли для участия в VZP!",
                ephemeral=True
            )
            return
        
        if active_vzp[vzp_id]['status'] != 'OPEN':
            await interaction_btn.response.send_message(
                f"❌ Набор на эту VZP закрыт! Текущий статус: {active_vzp[vzp_id]['status']}",
                ephemeral=True
            )
            return
        
        # Проверяем не является ли пользователь заменой
        vzp_swaps_current = swap_history.get(vzp_id, {})
        if interaction_btn.user.id in vzp_swaps_current.values():
            await interaction_btn.response.send_message(
                "❌ Вы уже в списке замен!",
                ephemeral=True
            )
            return
        
        if interaction_btn.user.id in active_vzp[vzp_id]['plus_users']:
            await interaction_btn.response.send_message(
                "❌ Вы уже подали заявку на эту VZP!",
                ephemeral=True
            )
            return
        
        active_vzp[vzp_id]['plus_users'][interaction_btn.user.id] = user_tier
        await update_vzp_message(vzp_id)
        
        try:
            notify_embed = discord.Embed(
                title="✅ ВЫ УСПЕШНО ЗАПИСАЛИСЬ НА VZP!",
                color=discord.Color.green()
            )
            notify_embed.add_field(name="ID VZP", value=vzp_id, inline=False)
            notify_embed.add_field(name="Тип", value=attack_def.name.split(' ')[1], inline=True)
            notify_embed.add_field(name="Противник", value=enemy, inline=True)
            notify_embed.add_field(name="Условия", value=", ".join(conditions_display), inline=False)
            notify_embed.add_field(name="Калибры", value=f"{caliber1.name} + {caliber2.name} + {caliber3.name}", inline=False)
            notify_embed.add_field(name="Время", value=time, inline=True)
            notify_embed.add_field(name="Ваш тир", value=f"Tier {user_tier}", inline=True)
            notify_embed.set_footer(text="Ожидайте начала VZP")
            
            await interaction_btn.user.send(embed=notify_embed)
        except:
            pass
        
        await interaction_btn.response.send_message(
            f"✅ Вы успешно записались на VZP! Проверьте ЛС.",
            ephemeral=True
        )
    
    button.callback = plus_callback
    view.add_item(button)
    
    await interaction.response.send_message(
        content="@everyone",
        embed=embed,
        view=view
    )
    
    message = await interaction.original_response()
    
    # Сохраняем все данные VZP
    active_vzp[vzp_id] = {
        'time': time,
        'members': members,
        'enemy': enemy,
        'attack_def': attack_def.value,
        'attack_def_name': attack_def.name,
        'conditions': conditions_values,
        'conditions_display': conditions_display,
        'calibers': [caliber1.value, caliber2.value, caliber3.value],
        'caliber_names': [caliber1.name, caliber2.name, caliber3.name],
        'message_id': message.id,
        'channel_id': interaction.channel_id,
        'plus_users': {},
        'status': 'OPEN',
        'category_id': None
    }
    
    swap_history[vzp_id] = {}
    
    await interaction.followup.send(
        f"✅ VZP создана! ID: `{vzp_id}`\n"
        f"📊 Формат: {attack_def.name.split(' ')[1]} vs {enemy} {time}\n"
        f"🎯 Условия: {', '.join(conditions_display)}\n"
        f"🔫 Калибры: {caliber1.name} + {caliber2.name} + {caliber3.name}",
        ephemeral=True
    )

@bot.tree.command(name="start_vzp", description="Запустить VZP (создать категорию и каналы)")
@app_commands.describe(vzp_id="ID VZP")
async def start_vzp(interaction: discord.Interaction, vzp_id: str):
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для запуска VZP!",
            ephemeral=True
        )
        return
    
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            f"❌ VZP с ID `{vzp_id}` не найдена!",
            ephemeral=True
        )
        return
    
    data = active_vzp[vzp_id]
    
    # Меняем статус на VZP IN PROCESS
    data['status'] = 'VZP IN PROCESS'
    await update_vzp_message(vzp_id)
    
    guild = interaction.guild
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    
    # Даём доступ участникам из основного списка
    members_to_move = []
    for user_id in data['plus_users']:
        member = guild.get_member(user_id)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True)
            members_to_move.append(member)
    
    # Также даём доступ заменённым игрокам (из SWAP)
    vzp_swaps = swap_history.get(vzp_id, {})
    for new_user_id in vzp_swaps.values():
        member = guild.get_member(new_user_id)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True)
            members_to_move.append(member)
    
    # Создаём категорию
    category = await guild.create_category_channel(
        name=f"VZP ID - {vzp_id}",
        overwrites=overwrites
    )
    
    data['category_id'] = category.id
    
    voice_channel = await category.create_voice_channel(name="vzp voice")
    text_flood = await category.create_text_channel(name="vzp flood")
    text_call = await category.create_text_channel(name="vzp call")
    
    moved_count = 0
    for member in members_to_move:
        if member.voice and member.voice.channel:
            try:
                await member.move_to(voice_channel)
                moved_count += 1
            except:
                pass
        await asyncio.sleep(0.3)
    
    # Уведомляем всех (основных + замены)
    notified = await notify_users_ls(
        vzp_id,
        "🎮 VZP НАЧАЛАСЬ!",
        f"VZP началась! Присоединяйтесь к голосовому каналу:\n{voice_channel.mention}",
        guild
    )
    
    await interaction.response.send_message(
        f"✅ VZP {vzp_id} запущена!\n"
        f"📊 Категория: {category.mention}\n"
        f"📢 Уведомлений отправлено: {notified}",
        ephemeral=True
    )

@bot.tree.command(name="stop_reactions", description="Остановить приём заявок на VZP")
@app_commands.describe(vzp_id="ID VZP")
async def stop_reactions(interaction: discord.Interaction, vzp_id: str):
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для этой команды!",
            ephemeral=True
        )
        return
    
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            f"❌ VZP с ID `{vzp_id}` не найдена!",
            ephemeral=True
        )
        return
    
    active_vzp[vzp_id]['status'] = 'LIST IN PROCESS'
    await update_vzp_message(vzp_id)
    
    await interaction.response.send_message(
        f"✅ Набор на VZP `{vzp_id}` закрыт!",
        ephemeral=True
    )

@bot.tree.command(name="return_reactions", description="Возобновить приём заявок на VZP")
@app_commands.describe(vzp_id="ID VZP")
async def return_reactions(interaction: discord.Interaction, vzp_id: str):
    """Возобновление приёма заявок"""
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для этой команды!",
            ephemeral=True
        )
        return
    
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            f"❌ VZP с ID `{vzp_id}` не найдена!",
            ephemeral=True
        )
        return
    
    data = active_vzp[vzp_id]
    
    # ПРОВЕРЯЕМ: если статус VZP IN PROCESS, не позволяем открывать набор
    if data['status'] == 'VZP IN PROCESS':
        await interaction.response.send_message(
            f"❌ Невозможно возобновить набор, VZP уже запущена!",
            ephemeral=True
        )
        return
    
    # Только если статус LIST IN PROCESS, меняем на OPEN
    if data['status'] == 'LIST IN PROCESS':
        data['status'] = 'OPEN'
        await update_vzp_message(vzp_id)
        await interaction.response.send_message(
            f"✅ Набор на VZP `{vzp_id}` возобновлён!",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ Текущий статус VZP не позволяет возобновить набор!",
            ephemeral=True
        )

@bot.tree.command(name="swap_player", description="Заменить игрока в VZP")
@app_commands.describe(
    vzp_id="ID VZP",
    old_player="Игрок, которого нужно заменить",
    new_player="Игрок, который заменит"
)
async def swap_player(interaction: discord.Interaction, vzp_id: str, old_player: discord.Member, new_player: discord.Member):
    """ЗАМЕНА ИГРОКА: старый удаляется из основного списка, новый добавляется ТОЛЬКО в SWAP"""
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для этой команды!",
            ephemeral=True
        )
        return
    
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            f"❌ VZP с ID `{vzp_id}` не найдена!",
            ephemeral=True
        )
        return
    
    data = active_vzp[vzp_id]
    
    # Проверка что старый игрок в списке
    if old_player.id not in data['plus_users']:
        await interaction.response.send_message(
            f"❌ Игрок {old_player.mention} не найден в списке VZP `{vzp_id}`!",
            ephemeral=True
        )
        return
    
    # Проверка что новый игрок не в основном списке И не в списке замен
    if new_player.id in data['plus_users']:
        await interaction.response.send_message(
            f"❌ Игрок {new_player.mention} уже в основном списке VZP!",
            ephemeral=True
        )
        return
    
    # Проверка что новый игрок не является заменой для кого-то
    vzp_swaps = swap_history.get(vzp_id, {})
    if new_player.id in vzp_swaps.values():
        await interaction.response.send_message(
            f"❌ Игрок {new_player.mention} уже является заменой для другого игрока!",
            ephemeral=True
        )
        return
    
    # Проверка роли нового игрока
    new_player_tier = None
    for tier_num, role_id in TIER_ROLES.items():
        if any(role.id == role_id for role in new_player.roles):
            new_player_tier = tier_num
            break
    
    if not new_player_tier:
        await interaction.response.send_message(
            f"❌ У игрока {new_player.mention} нет необходимой роли для участия в VZP!",
            ephemeral=True
        )
        return
    
    # УДАЛЯЕМ СТАРОГО ИГРОКА ИЗ ОСНОВНОГО СПИСКА
    del data['plus_users'][old_player.id]
    
    # ДОБАВЛЯЕМ ЗАМЕНУ В ИСТОРИЮ (НО НЕ В ОСНОВНОЙ СПИСОК!)
    if vzp_id not in swap_history:
        swap_history[vzp_id] = {}
    swap_history[vzp_id][old_player.id] = new_player.id
    
    # Обновляем права доступа к категории (если она создана)
    if data.get('category_id'):
        guild = interaction.guild
        category = guild.get_channel(data['category_id'])
        if category:
            try:
                # Забираем права у старого игрока
                await category.set_permissions(old_player, overwrite=None)
                
                # Даём права новому игроку
                await category.set_permissions(
                    new_player,
                    view_channel=True,
                    connect=True,
                    speak=True
                )
                
                # Если старый игрок в голосовом канале категории - выкидываем его
                voice_channels = [ch for ch in category.voice_channels]
                for voice_channel in voice_channels:
                    if old_player in voice_channel.members:
                        try:
                            await old_player.move_to(None)
                        except:
                            pass
            except Exception as e:
                print(f"❌ Ошибка обновления прав при замене: {e}")
    
    # Обновляем сообщение VZP
    await update_vzp_message(vzp_id)
    
    # Уведомляем обоих игроков в ЛС
    try:
        # Уведомляем старого игрока
        old_notify = discord.Embed(
            title="🔄 ВАС ЗАМЕНИЛИ В VZP",
            color=discord.Color.orange()
        )
        old_notify.add_field(name="ID VZP", value=vzp_id, inline=False)
        old_notify.add_field(name="Ваша замена", value=new_player.mention, inline=False)
        old_notify.add_field(name="Причина", value="Замена по решению администрации", inline=False)
        await old_player.send(embed=old_notify)
    except:
        pass
    
    try:
        # Уведомляем нового игрока
        new_notify = discord.Embed(
            title="✅ ВЫ ЗАМЕНИЛИ ИГРОКА В VZP",
            color=discord.Color.green()
        )
        new_notify.add_field(name="ID VZP", value=vzp_id, inline=False)
        new_notify.add_field(name="Вы заменили", value=old_player.mention, inline=False)
        new_notify.add_field(name="Время", value=data['time'], inline=True)
        new_notify.add_field(name="Противник", value=data['enemy'], inline=True)
        await new_player.send(embed=new_notify)
    except:
        pass
    
    # Только для админа
    await interaction.response.send_message(
        f"✅ Игрок заменён!\n"
        f"🗑️ {old_player.mention} удалён из основного списка\n"
        f"➕ {new_player.mention} добавлен в секцию SWAP",
        ephemeral=True
    )

@bot.tree.command(name="close_vzp", description="Закрыть VZP (удалить категорию и уведомить)")
@app_commands.describe(vzp_id="ID VZP")
async def close_vzp(interaction: discord.Interaction, vzp_id: str):
    """Закрытие VZP - удаление категории и изменение статуса на CLOSED"""
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для закрытия VZP!",
            ephemeral=True
        )
        return
    
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            f"❌ VZP с ID `{vzp_id}` не найдена!",
            ephemeral=True
        )
        return
    
    data = active_vzp[vzp_id]
    
    # МЕНЯЕМ СТАТУС НА CLOSED ПЕРЕД УДАЛЕНИЕМ
    data['status'] = 'CLOSED'
    await update_vzp_message(vzp_id)
    
    guild = interaction.guild
    
    # Удаляем категорию и каналы
    deleted_count = 0
    
    if data.get('category_id'):
        try:
            category = guild.get_channel(data['category_id'])
            if category:
                # Удаляем все каналы в категории
                for channel in guild.channels:
                    if hasattr(channel, 'category') and channel.category and channel.category.id == category.id:
                        try:
                            await channel.delete()
                            deleted_count += 1
                            await asyncio.sleep(0.3)
                        except:
                            pass
                
                # Удаляем категорию
                try:
                    await category.delete()
                    deleted_count += 1
                except:
                    pass
        except:
            pass
    
    # Уведомляем всех участников в ЛС о закрытии
    notified = await notify_users_ls(
        vzp_id,
        "🔚 VZP ЗАВЕРШЕНА",
        f"VZP завершена. Спасибо за участие!\n\n"
        f"📊 Итоги:\n"
        f"• Время: {data['time']}\n"
        f"• Противник: {data['enemy']}\n"
        f"• Участников: {len(data['plus_users'])}/{data['members']}",
        guild
    )
    
    # Сохраняем в архив
    closed_vzp[vzp_id] = data.copy()
    del active_vzp[vzp_id]
    
    # Удаляем историю замен для этой VZP
    if vzp_id in swap_history:
        del swap_history[vzp_id]
    
    # Только для админа
    await interaction.response.send_message(
        f"✅ VZP {vzp_id} закрыта!\n"
        f"🗑️ Удалено каналов: {deleted_count}\n"
        f"📢 Уведомлений отправлено: {notified}",
        ephemeral=True
    )

@bot.tree.command(name="del_list", description="Удалить пользователя из списка VZP")
@app_commands.describe(
    member="Пользователь",
    vzp_id="ID VZP"
)
async def del_list(interaction: discord.Interaction, member: discord.Member, vzp_id: str):
    """Удаление пользователя из списка"""
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для этой команды!",
            ephemeral=True
        )
        return
    
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            f"❌ VZP с ID `{vzp_id}` не найдена!",
            ephemeral=True
        )
        return
    
    # Проверка статуса (должен быть не OPEN)
    if active_vzp[vzp_id]['status'] == 'OPEN':
        await interaction.response.send_message(
            "❌ Сначала закройте набор командой `/stop_reactions`!",
            ephemeral=True
        )
        return
    
    # Проверка наличия пользователя в списке
    if member.id not in active_vzp[vzp_id]['plus_users']:
        await interaction.response.send_message(
            f"❌ Пользователь {member.mention} не в списке этой VZP!",
            ephemeral=True
        )
        return
    
    # Удаляем пользователя
    del active_vzp[vzp_id]['plus_users'][member.id]
    
    # Если пользователь был в истории замен, удаляем его оттуда
    if vzp_id in swap_history:
        # Удаляем если он был заменяющим
        if member.id in swap_history[vzp_id].values():
            key_to_remove = None
            for k, v in swap_history[vzp_id].items():
                if v == member.id:
                    key_to_remove = k
                    break
            if key_to_remove:
                del swap_history[vzp_id][key_to_remove]
        
        # Удаляем если он был заменяемым
        if member.id in swap_history[vzp_id]:
            del swap_history[vzp_id][member.id]
    
    await update_vzp_message(vzp_id)
    
    # Уведомляем пользователя в ЛС
    try:
        notify_embed = discord.Embed(
            title="❌ ВАС УДАЛИЛИ ИЗ СПИСКА VZP",
            color=discord.Color.red()
        )
        notify_embed.add_field(name="ID VZP", value=vzp_id, inline=False)
        notify_embed.add_field(name="Причина", value="Удалён администратором", inline=False)
        
        await member.send(embed=notify_embed)
    except:
        pass
    
    # Только для админа
    await interaction.response.send_message(
        f"✅ {member.mention} удалён из списка VZP `{vzp_id}`!",
        ephemeral=True
    )

@bot.tree.command(name="list_vzp", description="Показать активные VZP")
async def list_vzp(interaction: discord.Interaction):
    """Список активных VZP"""
    if not active_vzp:
        await interaction.response.send_message(
            "📭 Нет активных VZP",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title="📋 АКТИВНЫЕ VZP",
        color=discord.Color.blue()
    )
    
    for vzp_id, data in active_vzp.items():
        status = data.get('status', 'OPEN')
        status_emoji = {
            'OPEN': '🟢',
            'LIST IN PROCESS': '🟡', 
            'VZP IN PROCESS': '🔵',
            'CLOSED': '🔴'
        }.get(status, '⚪')
        
        embed.add_field(
            name=f"**{vzp_id}** {status_emoji}",
            value=f"⏰ **Время:** {data['time']}\n"
                  f"⚔️ **Тип:** {data.get('attack_def_name', 'АТАКА').split(' ')[1]}\n"
                  f"🎯 **Условия:** {', '.join(data.get('conditions_display', ['Условие']))}\n"
                  f"🔫 **Калибры:** {' + '.join(data.get('caliber_names', []))}\n"
                  f"👥 **Участники:** {len(data['plus_users'])}/{data['members']}\n"
                  f"📊 **Статус:** {status}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Пингануть всех участников")
async def ping(interaction: discord.Interaction):
    """Пинг всех участников"""
    if not await is_allowed_channel(interaction):
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{ALLOWED_CHANNEL}>!",
            ephemeral=True
        )
        return
    
    if not await has_high_role(interaction):
        await interaction.response.send_message(
            "❌ У вас нет прав для этой команды!",
            ephemeral=True
        )
        return
    
    # Отправляем 5 упоминаний @everyone
    await interaction.response.send_message("**РЕАКИ НА ТЕРРУ!**")
    
    for i in range(5):
        await interaction.followup.send("@everyone")
        await asyncio.sleep(0.5)

@bot.tree.command(name="help_vzp", description="Помощь по командам VZP бота")
async def help_vzp(interaction: discord.Interaction):
    """Помощь по командам"""
    embed = discord.Embed(
        title="📚 ПОМОЩЬ ПО КОМАНДАМ VZP БОТА",
        color=discord.Color.purple()
    )
    
    commands_list = [
        ("`/vzp_start`", "Создать новую VZP с условиями забива", "`/vzp_start` (откроет выбор всех параметров)"),
        ("`/start_vzp`", "Запустить VZP (создать категорию)", "`/start_vzp VZP_ID`"),
        ("`/close_vzp`", "Закрыть VZP (удалить категорию)", "`/close_vzp VZP_ID`"),
        ("`/stop_reactions`", "Остановить приём заявок", "`/stop_reactions VZP_ID`"),
        ("`/return_reactions`", "Возобновить приём заявок", "`/return_reactions VZP_ID`"),
        ("`/swap_player`", "Заменить игрока в VZP", "`/swap_player VZP_ID @old @new`"),
        ("`/del_list`", "Удалить пользователя из списка", "`/del_list @user VZP_ID`"),
        ("`/ping`", "Пингануть всех участников", "`/ping`"),
        ("`/list_vzp`", "Показать активные VZP", "`/list_vzp`"),
        ("`/help_vzp`", "Эта справка", "`/help_vzp`")
    ]
    
    for cmd, desc, example in commands_list:
        embed.add_field(name=f"{cmd} - {desc}", value=f"Пример: {example}", inline=False)
    
    embed.add_field(
        name="📊 СТАТУСЫ И ЦВЕТА",
        value="```\n🟢 OPEN - набор открыт\n🟡 LIST IN PROCESS - список формируется\n🔵 VZP IN PROCESS - VZP идёт\n🔴 CLOSED - VZP завершена\n```",
        inline=False
    )
    
    embed.add_field(
        name="🎯 ПАРАМЕТРЫ VZP_START",
        value="1. ⚔️/🛡️ Атака или Оборона\n"
              "2. Условия (можно выбрать 1-3):\n"
              "   🍷 Алкоголь/анальгетик\n"
              "   🚬 Косяки/SPANK\n"
              "   💊 Аптечки\n"
              "   🛡️ Броня\n"
              "3. 🔫 3 разных калибра (5.56mm, 7.62mm, 9mm, 11.43mm, 12mm)",
        inline=False
    )
    
    embed.set_footer(text="Для админов с определёнными ролями")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ===================== ЗАПУСК =====================
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'👑 ID бота: {bot.user.id}')
    print(f'📊 Серверов: {len(bot.guilds)}')
    print('🎮 Доступные команды (через /):')
    print('   /vzp_start - создать VZP с выбором условий (тегает @everyone)')
    print('   /start_vzp - запустить VZP (статус: VZP IN PROCESS, синий)')
    print('   /close_vzp - закрыть VZP (статус: CLOSED, красный)')
    print('   /stop_reactions - остановить заявки (LIST IN PROCESS, жёлтый)')
    print('   /return_reactions - возобновить заявки (OPEN, зелёный)')
    print('   /swap_player - заменить игрока (старый удаляется, новый только в SWAP)')
    print('   /del_list - удалить из списка')
    print('   /ping - пингануть всех (5 раз @everyone)')
    print('   /list_vzp - список VZP')
    print('   /help_vzp - помощь')
    
    await bot.change_presence(activity=discord.Game(name="/vzp_start | VZP Manager"))

if __name__ == "__main__":
    print("🚀 Запуск бота...")
    bot.run(TOKEN)