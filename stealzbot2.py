import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle
import asyncio
import uuid
import os
import json
from dotenv import load_dotenv
from typing import Optional, Dict, List, Set
from datetime import datetime

# ===================== ЗАГРУЗКА ТОКЕНА ИЗ .env =====================
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("❌ ОШИБКА: DISCORD_TOKEN не найден в .env файле!")
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
MAX_ACTIVE_VZP = 15  # Ограничение для стабильности
MAX_PARTICIPANTS_PER_VZP = 100  # Ограничение участников на VZP

# ===================== PERSISTENT VIEWS =====================
class VZPView(ui.View):
    """Persistent View с одной кнопкой для VZP"""
    def __init__(self, vzp_id: str):
        super().__init__(timeout=None)
        self.vzp_id = vzp_id
        self.user_states: Dict[int, bool] = {}  # Хранит состояние кнопки для каждого пользователя
        
        # Кнопка с фиксированным custom_id
        self.button = ui.Button(
            style=ButtonStyle.green,
            label="ПОДАТЬ ПЛЮС",
            custom_id=f"vzp_button_{vzp_id}",
            emoji="➕"
        )
        self.button.callback = self.button_callback
        self.add_item(self.button)
    
    def update_button_style(self, user_id: int, is_in_list: bool):
        """Обновляет стиль кнопки для конкретного пользователя в памяти"""
        self.user_states[user_id] = is_in_list
    
    def get_button_style_for_user(self, user_id: int) -> tuple:
        """Возвращает стиль кнопки для конкретного пользователя"""
        is_in_list = self.user_states.get(user_id, False)
        
        if is_in_list:
            return ButtonStyle.red, "УБРАТЬ ПЛЮС", "❌"
        else:
            return ButtonStyle.green, "ПОДАТЬ ПЛЮС", "➕"
    
    async def button_callback(self, interaction: discord.Interaction):
        """Обработка нажатия кнопки"""
        await handle_vzp_button(interaction, self.vzp_id)

# ===================== ХРАНИЛИЩА ДАННЫХ =====================
class VZPData:
    """Класс для хранения данных VZP"""
    def __init__(self, data: dict):
        self.time: str = data.get('time', '')
        self.members: int = data.get('members', 0)
        self.enemy: str = data.get('enemy', '')
        self.attack_def: str = data.get('attack_def', '')
        self.attack_def_name: str = data.get('attack_def_name', '')
        self.conditions: List[str] = data.get('conditions', [])
        self.conditions_display: List[str] = data.get('conditions_display', [])
        self.calibers: List[str] = data.get('calibers', [])
        self.caliber_names: List[str] = data.get('caliber_names', [])
        self.message_id: int = data.get('message_id', 0)
        self.channel_id: int = data.get('channel_id', 0)
        self.category_id: Optional[int] = data.get('category_id')
        self.plus_users: Dict[int, int] = data.get('plus_users', {})
        self.status: str = data.get('status', 'OPEN')
        self.created_at: str = data.get('created_at', datetime.now().isoformat())
        self.view: Optional[VZPView] = None

# Глобальные хранилища
active_vzp: Dict[str, VZPData] = {}
closed_vzp: Dict[str, dict] = {}
swap_history: Dict[str, Dict[int, int]] = {}
vzp_views: Dict[str, VZPView] = {}  # Хранит все активные Views

# Файлы для сохранения данных
DATA_FILE = "vzp_data.json"
SWAP_FILE = "swap_data.json"
VIEWS_FILE = "views_cache.json"

def save_data():
    """Сохраняет данные в файлы"""
    try:
        # Сохраняем данные VZP
        vzp_data = {}
        for vzp_id, vzp in active_vzp.items():
            vzp_data[vzp_id] = {
                'time': vzp.time,
                'members': vzp.members,
                'enemy': vzp.enemy,
                'attack_def': vzp.attack_def,
                'attack_def_name': vzp.attack_def_name,
                'conditions': vzp.conditions,
                'conditions_display': vzp.conditions_display,
                'calibers': vzp.calibers,
                'caliber_names': vzp.caliber_names,
                'message_id': vzp.message_id,
                'channel_id': vzp.channel_id,
                'category_id': vzp.category_id,
                'plus_users': vzp.plus_users,
                'status': vzp.status,
                'created_at': vzp.created_at
            }
        
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'active': vzp_data,
                'closed': closed_vzp
            }, f, ensure_ascii=False, indent=2)
        
        # Сохраняем историю замен
        with open(SWAP_FILE, 'w', encoding='utf-8') as f:
            json.dump(swap_history, f, ensure_ascii=False, indent=2)
        
        # Сохраняем кэш View состояний
        views_cache = {}
        for vzp_id, view in vzp_views.items():
            views_cache[vzp_id] = view.user_states
        
        with open(VIEWS_FILE, 'w', encoding='utf-8') as f:
            json.dump(views_cache, f, ensure_ascii=False, indent=2)
        
        print(f"💾 Данные сохранены: {len(active_vzp)} активных VZP")
    except Exception as e:
        print(f"❌ Ошибка сохранения данных: {e}")

def load_data():
    """Загружает данные из файлов"""
    global active_vzp, closed_vzp, swap_history
    
    try:
        # Загружаем данные VZP
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                active_data = data.get('active', {})
                for vzp_id, vzp_data in active_data.items():
                    # Конвертируем user_id в int
                    if 'plus_users' in vzp_data:
                        vzp_data['plus_users'] = {int(k): int(v) for k, v in vzp_data['plus_users'].items()}
                    
                    active_vzp[vzp_id] = VZPData(vzp_data)
                
                closed_vzp = data.get('closed', {})
        
        # Загружаем историю замен
        if os.path.exists(SWAP_FILE):
            with open(SWAP_FILE, 'r', encoding='utf-8') as f:
                swap_data = json.load(f)
                swap_history = {k: {int(k2): int(v2) for k2, v2 in v.items()} for k, v in swap_data.items()}
        
        print(f"📂 Данные загружены: {len(active_vzp)} активных VZP")
    except Exception as e:
        print(f"❌ Ошибка загрузки данных: {e}")
        active_vzp = {}
        closed_vzp = {}
        swap_history = {}

def load_views_cache():
    """Загружает кэш состояний кнопок"""
    try:
        if os.path.exists(VIEWS_FILE):
            with open(VIEWS_FILE, 'r', encoding='utf-8') as f:
                views_cache = json.load(f)
                
                for vzp_id, user_states in views_cache.items():
                    if vzp_id in vzp_views:
                        # Конвертируем ключи в int
                        vzp_views[vzp_id].user_states = {int(k): v for k, v in user_states.items()}
        
        print(f"📂 Кэш View загружен: {len(vzp_views)} Views")
    except Exception as e:
        print(f"❌ Ошибка загрузки кэша View: {e}")

# ===================== НАСТРОЙКА БОТА =====================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class VZPBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
    
    async def setup_hook(self):
        # Загружаем сохраненные данные
        load_data()
        load_views_cache()
        
        # Восстанавливаем все активные Views для OPEN VZP
        for vzp_id, vzp_data in active_vzp.items():
            if vzp_data.status == 'OPEN':
                view = VZPView(vzp_id)
                self.add_view(view)
                vzp_views[vzp_id] = view
                
                # Восстанавливаем состояния кнопок
                for user_id in vzp_data.plus_users.keys():
                    view.update_button_style(user_id, True)
        
        # Синхронизируем команды
        try:
            synced = await self.tree.sync()
            print(f"✅ Синхронизировано {len(synced)} команд")
        except Exception as e:
            print(f"❌ Ошибка синхронизации: {e}")

bot = VZPBot()

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
async def is_allowed_channel(interaction: discord.Interaction) -> bool:
    """Проверяет разрешенный ли канал"""
    return interaction.channel_id == ALLOWED_CHANNEL

async def has_high_role(interaction: discord.Interaction) -> bool:
    """Проверяет наличие админской роли"""
    return any(role.id in HIGH_ROLES for role in interaction.user.roles)

async def get_user_tier(user: discord.Member) -> Optional[int]:
    """Возвращает тир пользователя"""
    for tier_num, role_id in TIER_ROLES.items():
        if any(role.id == role_id for role in user.roles):
            return tier_num
    return None

async def create_vzp_embed(vzp_id: str, vzp_data: VZPData) -> discord.Embed:
    """Создает embed для VZP"""
    # Статус и цвет
    status_colors = {
        'OPEN': discord.Color.green(),
        'LIST IN PROCESS': discord.Color.gold(),
        'VZP IN PROCESS': discord.Color.blue(),
        'CLOSED': discord.Color.red()
    }
    color = status_colors.get(vzp_data.status, discord.Color.green())
    
    # Формируем описание
    attack_def_display = vzp_data.attack_def_name.split(' ')[1]
    description = f"**{attack_def_display} vs {vzp_data.enemy} {len(vzp_data.plus_users)}/{vzp_data.members} {vzp_data.time}**\n"
    description += f"\n**{', '.join(vzp_data.conditions_display)}**\n"
    description += f"**{vzp_data.caliber_names[0]} + {vzp_data.caliber_names[1]} + {vzp_data.caliber_names[2]}**"
    
    # Создаём embed
    embed = discord.Embed(description=description, color=color)
    
    # Сортируем по тирам
    tier_lists = {1: [], 2: [], 3: []}
    for user_id, tier in vzp_data.plus_users.items():
        tier_lists[tier].append(user_id)
    
    # Добавляем тиры
    for tier_num in [1, 2, 3]:
        members_list = []
        for user_id in tier_lists[tier_num]:
            member = bot.get_guild(interaction.guild.id).get_member(user_id) if 'interaction' in locals() else None
            if member:
                members_list.append(f"• {member.mention}")
            else:
                members_list.append(f"• <@{user_id}>")
        
        tier_name = {1: "TIER 1", 2: "TIER 2", 3: "TIER 3"}[tier_num]
        embed.add_field(
            name=f"**{tier_name}** ({len(tier_lists[tier_num])})",
            value="\n".join(members_list) if members_list else "—",
            inline=False
        )
    
    # Секция SWAP
    vzp_swaps = swap_history.get(vzp_id, {})
    if vzp_swaps:
        swap_list = []
        for old_user_id, new_user_id in vzp_swaps.items():
            old_member = bot.get_guild(interaction.guild.id).get_member(old_user_id) if 'interaction' in locals() else None
            new_member = bot.get_guild(interaction.guild.id).get_member(new_user_id) if 'interaction' in locals() else None
            
            old_name = old_member.mention if old_member else f"<@{old_user_id}>"
            new_name = new_member.mention if new_member else f"<@{new_user_id}>"
            swap_list.append(f"• {new_name} → {old_name}")
        
        if swap_list:
            embed.add_field(name="**SWAP**", value="\n".join(swap_list), inline=False)
    
    # Статус и ID
    embed.add_field(name="**STATUS**", value=f"```{vzp_data.status}```", inline=False)
    embed.add_field(name="**ID**", value=f"```{vzp_id}```", inline=False)
    
    return embed

async def update_vzp_message(vzp_id: str, interaction: discord.Interaction = None):
    """Обновляет сообщение VZP"""
    if vzp_id not in active_vzp:
        return
    
    vzp_data = active_vzp[vzp_id]
    
    try:
        channel = bot.get_channel(vzp_data.channel_id)
        if not channel:
            return
        
        message = await channel.fetch_message(vzp_data.message_id)
        
        # Создаем embed
        embed = await create_vzp_embed(vzp_id, vzp_data)
        
        # Определяем View
        view = None
        if vzp_data.status == 'OPEN':
            if vzp_id not in vzp_views:
                view = VZPView(vzp_id)
                vzp_views[vzp_id] = view
                bot.add_view(view)
            else:
                view = vzp_views[vzp_id]
        
        # Обновляем сообщение
        await message.edit(embed=embed, view=view)
        
        # Если есть interaction и статус OPEN, обновляем кнопку
        if interaction and vzp_data.status == 'OPEN' and view:
            user_id = interaction.user.id
            is_in_list = user_id in vzp_data.plus_users
            view.update_button_style(user_id, is_in_list)
            
            # Отправляем ephemeral сообщение с обновленной кнопкой
            style, label, emoji = view.get_button_style_for_user(user_id)
            
            # Создаем временный View для ephemeral ответа
            temp_view = ui.View(timeout=None)
            temp_button = ui.Button(
                style=style,
                label=label,
                custom_id=f"temp_{vzp_id}_{user_id}",
                emoji=emoji,
                disabled=True
            )
            temp_view.add_item(temp_button)
            
            # Отправляем ephemeral ответ
            await interaction.response.send_message(
                content=f"✅ Состояние обновлено!",
                view=temp_view,
                ephemeral=True
            )
    
    except discord.NotFound:
        print(f"❌ Сообщение VZP {vzp_id} не найдено")
    except discord.Forbidden:
        print(f"❌ Нет прав для обновления сообщения VZP {vzp_id}")
    except Exception as e:
        print(f"❌ Ошибка обновления VZP {vzp_id}: {e}")

async def handle_vzp_button(interaction: discord.Interaction, vzp_id: str):
    """Обрабатывает нажатие кнопки VZP"""
    if vzp_id not in active_vzp:
        await interaction.response.send_message(
            "❌ Эта VZP больше не активна!",
            ephemeral=True
        )
        return
    
    vzp_data = active_vzp[vzp_id]
    user = interaction.user
    
    # Проверяем права
    tier = await get_user_tier(user)
    if not tier:
        await interaction.response.send_message(
            "❌ У вас нет необходимой роли для участия в VZP!",
            ephemeral=True
        )
        return
    
    if vzp_data.status != 'OPEN':
        await interaction.response.send_message(
            f"❌ Набор на эту VZP закрыт! Текущий статус: {vzp_data.status}",
            ephemeral=True
        )
        return
    
    # Проверяем замены
    vzp_swaps = swap_history.get(vzp_id, {})
    if user.id in vzp_swaps.values():
        await interaction.response.send_message(
            "❌ Вы уже в списке замен!",
            ephemeral=True
        )
        return
    
    # Проверяем лимит участников
    if len(vzp_data.plus_users) >= MAX_PARTICIPANTS_PER_VZP:
        await interaction.response.send_message(
            f"❌ Достигнут максимальный лимит участников ({MAX_PARTICIPANTS_PER_VZP})!",
            ephemeral=True
        )
        return
    
    is_in_list = user.id in vzp_data.plus_users
    
    if is_in_list:
        # Удаляем из списка
        del vzp_data.plus_users[user.id]
        action = "удалились"
    else:
        # Проверяем лимит VZP
        if len(vzp_data.plus_users) >= vzp_data.members:
            await interaction.response.send_message(
                "❌ Достигнут лимит участников для этой VZP!",
                ephemeral=True
            )
            return
        
        # Добавляем в список
        vzp_data.plus_users[user.id] = tier
        action = "записались"
    
    # Обновляем состояние кнопки в View
    if vzp_id in vzp_views:
        vzp_views[vzp_id].update_button_style(user.id, not is_in_list)

    # Обновляем сообщение VZP
    await update_vzp_message(vzp_id, interaction)
    save_data()

async def notify_users_ls(vzp_id: str, title: str, message: str, guild: discord.Guild, user_ids: Set[int] = None) -> int:
    """Отправляет уведомления пользователям в ЛС"""
    if vzp_id not in active_vzp:
        return 0
    
    vzp_data = active_vzp[vzp_id]
    notified = 0
    
    target_ids = user_ids if user_ids else set(vzp_data.plus_users.keys())
    
    for user_id in target_ids:
        member = guild.get_member(user_id)
        if member:
            try:
                embed = discord.Embed(title=title, description=message, color=discord.Color.blue())
                embed.add_field(name="VZP ID", value=vzp_id, inline=False)
                embed.add_field(name="Время", value=vzp_data.time, inline=True)
                embed.add_field(name="Противник", value=vzp_data.enemy, inline=True)
                embed.set_footer(text="VZP Manager")
                
                await member.send(embed=embed)
                notified += 1
            except:
                pass
            
            await asyncio.sleep(0.1)  # Задержка для избежания лимитов
    
    return notified

# ===================== КОМАНДЫ =====================

@bot.tree.command(name="vzp_start", description="Создать новую VZP с выбором условий")
@app_commands.describe(
    time="Время VZP (например: 20:00)",
    members="Количество участников",
    enemy="Имя противника",
    attack_def="Выберите АТАКУ или ОБОРОНУ",
    condition1="Выберите первое условие забива",
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
        app_commands.Choice(name="Алкоголь/анальгетик", value="alcohol"),
        app_commands.Choice(name="Косяки/SPANK", value="joints"),
        app_commands.Choice(name="Аптечки", value="medkits"),
        app_commands.Choice(name="Броня", value="armor")
    ],
    condition2=[
        app_commands.Choice(name="Алкоголь/анальгетик", value="alcohol"),
        app_commands.Choice(name="Косяки/SPANK", value="joints"),
        app_commands.Choice(name="Аптечки", value="medkits"),
        app_commands.Choice(name="Броня", value="armor"),
    ],
    condition3=[
        app_commands.Choice(name="Алкоголь/анальгетик", value="alcohol"),
        app_commands.Choice(name="Косяки/SPANK", value="joints"),
        app_commands.Choice(name="Аптечки", value="medkits"),
        app_commands.Choice(name="Броня", value="armor"),
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
    
    # Проверяем лимит активных VZP
    if len(active_vzp) >= MAX_ACTIVE_VZP:
        await interaction.response.send_message(
            f"❌ Достигнут лимит активных VZP ({MAX_ACTIVE_VZP})! "
            f"Закройте некоторые VZP командой `/close_vzp`",
            ephemeral=True
        )
        return
    
    # Проверяем лимит участников
    if members > MAX_PARTICIPANTS_PER_VZP:
        await interaction.response.send_message(
            f"❌ Максимальное количество участников: {MAX_PARTICIPANTS_PER_VZP}",
            ephemeral=True
        )
        return
    
    # Проверяем калибры
    calibers = [caliber1.value, caliber2.value, caliber3.value]
    if len(set(calibers)) < 3:
        await interaction.response.send_message(
            "❌ Выберите три РАЗНЫХ калибра!",
            ephemeral=True
        )
        return
    
    vzp_id = str(uuid.uuid4())[:8]
    
    # Преобразуем названия условий
    condition_names = {
        "alcohol": "Алкоголь/анальгетик",
        "joints": "Косяки/SPANK",
        "medkits": "Аптечки",
        "armor": "Броня"
    }
    
    # Собираем условия
    conditions_display = [condition_names.get(condition1.value, condition1.value)]
    conditions_values = [condition1.value]
    
    if condition2 and condition2.value not in conditions_values:
        conditions_display.append(condition_names.get(condition2.value, condition2.value))
        conditions_values.append(condition2.value)
    
    if condition3 and condition3.value not in conditions_values:
        conditions_display.append(condition_names.get(condition3.value, condition3.value))
        conditions_values.append(condition3.value)
    
    # Создаем embed
    attack_def_display = attack_def.name.split(' ')[1]
    description = f"**{attack_def_display} vs {enemy} 0/{members} {time}**\n"
    description += f"\n**{', '.join(conditions_display)}**\n"
    description += f"**{caliber1.name} + {caliber2.name} + {caliber3.name}**"
    
    embed = discord.Embed(description=description, color=discord.Color.green())
    
    for tier_num in [1, 2, 3]:
        embed.add_field(name=f"**TIER {tier_num}** (0)", value="—", inline=False)
    
    embed.add_field(name="**STATUS**", value=f"```OPEN```", inline=False)
    embed.add_field(name="**ID**", value=f"```{vzp_id}```", inline=False)
    
    # Создаем View
    view = VZPView(vzp_id)
    vzp_views[vzp_id] = view
    
    # Отправляем сообщение
    await interaction.response.send_message(content="@everyone", embed=embed, view=view)
    message = await interaction.original_response()
    
    # Сохраняем данные VZP
    vzp_data = VZPData({
        'time': time,
        'members': members,
        'enemy': enemy,
        'attack_def': attack_def.value,
        'attack_def_name': attack_def.name,
        'conditions': conditions_values,
        'conditions_display': conditions_display,
        'calibers': calibers,
        'caliber_names': [caliber1.name, caliber2.name, caliber3.name],
        'message_id': message.id,
        'channel_id': interaction.channel_id,
        'plus_users': {},
        'status': 'OPEN',
        'created_at': datetime.now().isoformat()
    })
    vzp_data.view = view
    
    active_vzp[vzp_id] = vzp_data
    swap_history[vzp_id] = {}
    save_data()
    
    await interaction.followup.send(
        f"✅ VZP создана! ID: `{vzp_id}`\n"
        f"📊 Формат: {attack_def_display} vs {enemy} {time}\n"
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
    
    vzp_data = active_vzp[vzp_id]
    vzp_data.status = 'VZP IN PROCESS'
    
    # Обновляем сообщение (убираем кнопку)
    await update_vzp_message(vzp_id)
    
    # Создаем категорию и каналы
    guild = interaction.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    
    members_to_move = []
    for user_id in vzp_data.plus_users:
        member = guild.get_member(user_id)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True)
            members_to_move.append(member)
    
    vzp_swaps = swap_history.get(vzp_id, {})
    for new_user_id in vzp_swaps.values():
        member = guild.get_member(new_user_id)
        if member:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True)
            members_to_move.append(member)
    
    category = await guild.create_category_channel(
        name=f"VZP ID - {vzp_id}",
        overwrites=overwrites
    )
    
    vzp_data.category_id = category.id
    voice_channel = await category.create_voice_channel(name="vzp voice")
    await category.create_text_channel(name="vzp flood")
    await category.create_text_channel(name="vzp call")
    
    # Перемещаем участников
    moved_count = 0
    for member in members_to_move:
        if member.voice and member.voice.channel:
            try:
                await member.move_to(voice_channel)
                moved_count += 1
            except:
                pass
        await asyncio.sleep(0.1)
    
    # Отправляем уведомления
    notified = await notify_users_ls(
        vzp_id,
        "🎮 VZP НАЧАЛАСЬ!",
        f"VZP началась! Присоединяйтесь к голосовому каналу:\n{voice_channel.mention}",
        guild
    )
    
    await interaction.response.send_message(
        f"✅ VZP {vzp_id} запущена!\n"
        f"📊 Категория: {category.mention}\n"
        f"👥 Перемещено участников: {moved_count}\n"
        f"📢 Уведомлений отправлено: {notified}",
        ephemeral=True
    )
    
    save_data()

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
    
    vzp_data = active_vzp[vzp_id]
    
    if vzp_data.status != 'OPEN':
        await interaction.response.send_message(
            f"❌ VZP уже не в статусе OPEN! Текущий статус: {vzp_data.status}",
            ephemeral=True
        )
        return
    
    vzp_data.status = 'LIST IN PROCESS'
    await update_vzp_message(vzp_id)
    save_data()
    
    await interaction.response.send_message(
        f"✅ Набор на VZP `{vzp_id}` закрыт!",
        ephemeral=True
    )

@bot.tree.command(name="return_reactions", description="Возобновить приём заявок на VZP")
@app_commands.describe(vzp_id="ID VZP")
async def return_reactions(interaction: discord.Interaction, vzp_id: str):
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
    
    vzp_data = active_vzp[vzp_id]
    
    if vzp_data.status not in ['LIST IN PROCESS', 'VZP IN PROCESS']:
        await interaction.response.send_message(
            f"❌ VZP не в статусе LIST IN PROCESS! Текущий статус: {vzp_data.status}",
            ephemeral=True
        )
        return
    
    if vzp_data.status == 'VZP IN PROCESS':
        await interaction.response.send_message(
            f"❌ Невозможно возобновить набор, VZP уже запущена!",
            ephemeral=True
        )
        return
    
    vzp_data.status = 'OPEN'
    await update_vzp_message(vzp_id)
    save_data()
    
    await interaction.response.send_message(
        f"✅ Набор на VZP `{vzp_id}` возобновлён!",
        ephemeral=True
    )

@bot.tree.command(name="swap_player", description="Заменить игрока в VZP")
@app_commands.describe(
    vzp_id="ID VZP",
    old_player="Игрок, которого нужно заменить",
    new_player="Игрок, который заменит"
)
async def swap_player(interaction: discord.Interaction, vzp_id: str, old_player: discord.Member, new_player: discord.Member):
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
    
    vzp_data = active_vzp[vzp_id]
    
    if old_player.id not in vzp_data.plus_users:
        await interaction.response.send_message(
            f"❌ Игрок {old_player.mention} не найден в списке VZP `{vzp_id}`!",
            ephemeral=True
        )
        return
    
    if new_player.id in vzp_data.plus_users:
        await interaction.response.send_message(
            f"❌ Игрок {new_player.mention} уже в основном списке VZP!",
            ephemeral=True
        )
        return
    
    new_player_tier = await get_user_tier(new_player)
    if not new_player_tier:
        await interaction.response.send_message(
            f"❌ У игрока {new_player.mention} нет необходимой роли для участия в VZP!",
            ephemeral=True
        )
        return
    
    # Удаляем старого игрока из основного списка
    del vzp_data.plus_users[old_player.id]
    
    # Добавляем замену в историю
    if vzp_id not in swap_history:
        swap_history[vzp_id] = {}
    swap_history[vzp_id][old_player.id] = new_player.id
    
    # Обновляем права в категории если она существует
    if vzp_data.category_id:
        category = interaction.guild.get_channel(vzp_data.category_id)
        if category:
            try:
                await category.set_permissions(old_player, overwrite=None)
                await category.set_permissions(
                    new_player,
                    view_channel=True,
                    connect=True,
                    speak=True
                )
                
                # Ищем голосовой канал
                voice_channels = [ch for ch in category.voice_channels if isinstance(ch, discord.VoiceChannel)]
                for voice_channel in voice_channels:
                    if old_player in voice_channel.members:
                        try:
                            await old_player.move_to(None)
                        except:
                            pass
            except Exception as e:
                print(f"❌ Ошибка обновления прав: {e}")
    
    # Обновляем сообщение
    await update_vzp_message(vzp_id)
    
    # Отправляем уведомления
    try:
        old_embed = discord.Embed(
            title="🔄 ВАС ЗАМЕНИЛИ В VZP",
            color=discord.Color.orange()
        )
        old_embed.add_field(name="ID VZP", value=vzp_id, inline=False)
        old_embed.add_field(name="Ваша замена", value=new_player.mention, inline=False)
        await old_player.send(embed=old_embed)
    except:
        pass
    
    try:
        new_embed = discord.Embed(
            title="✅ ВЫ ЗАМЕНИЛИ ИГРОКА В VZP",
            color=discord.Color.green()
        )
        new_embed.add_field(name="ID VZP", value=vzp_id, inline=False)
        new_embed.add_field(name="Вы заменили", value=old_player.mention, inline=False)
        new_embed.add_field(name="Время", value=vzp_data.time, inline=True)
        new_embed.add_field(name="Противник", value=vzp_data.enemy, inline=True)
        await new_player.send(embed=new_embed)
    except:
        pass
    
    await interaction.response.send_message(
        f"✅ Игрок заменён!\n"
        f"🗑️ {old_player.mention} удалён из основного списка\n"
        f"➕ {new_player.mention} добавлен в секцию SWAP",
        ephemeral=True
    )
    
    save_data()

@bot.tree.command(name="close_vzp", description="Закрыть VZP (удалить категорию и уведомить)")
@app_commands.describe(vzp_id="ID VZP")
async def close_vzp(interaction: discord.Interaction, vzp_id: str):
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
    
    vzp_data = active_vzp[vzp_id]
    vzp_data.status = 'CLOSED'
    
    # Удаляем View
    if vzp_id in vzp_views:
        del vzp_views[vzp_id]
    
    # Обновляем сообщение
    await update_vzp_message(vzp_id)
    
    # Удаляем категорию и каналы
    guild = interaction.guild
    deleted_count = 0
    
    if vzp_data.category_id:
        try:
            category = guild.get_channel(vzp_data.category_id)
            if category:
                # Удаляем все каналы в категории
                for channel in category.channels:
                    try:
                        await channel.delete()
                        deleted_count += 1
                        await asyncio.sleep(0.1)
                    except:
                        pass
                
                # Удаляем саму категорию
                try:
                    await category.delete()
                    deleted_count += 1
                except:
                    pass
        except:
            pass

    # Переносим в закрытые
    closed_vzp[vzp_id] = {
        'time': vzp_data.time,
        'enemy': vzp_data.enemy,
        'members': vzp_data.members,
        'participants': len(vzp_data.plus_users),
        'closed_at': datetime.now().isoformat()
    }
    
    # Удаляем из активных
    del active_vzp[vzp_id]
    
    if vzp_id in swap_history:
        del swap_history[vzp_id]
    
    save_data()
    
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
    
    vzp_data = active_vzp[vzp_id]
    
    if member.id not in vzp_data.plus_users:
        await interaction.response.send_message(
            f"❌ Пользователь {member.mention} не в списке этой VZP!",
            ephemeral=True
        )
        return
    
    # Удаляем из основного списка
    del vzp_data.plus_users[member.id]
    
    # Удаляем из истории замен если есть
    if vzp_id in swap_history:
        # Если member был заменой
        if member.id in swap_history[vzp_id].values():
            key_to_remove = None
            for k, v in swap_history[vzp_id].items():
                if v == member.id:
                    key_to_remove = k
                    break
            if key_to_remove:
                del swap_history[vzp_id][key_to_remove]
        
        # Если member был тем, кого заменяли
        if member.id in swap_history[vzp_id]:
            del swap_history[vzp_id][member.id]
    
    # Обновляем состояние кнопки если View существует
    if vzp_id in vzp_views:
        vzp_views[vzp_id].update_button_style(member.id, False)
    
    # Обновляем сообщение
    await update_vzp_message(vzp_id)
    save_data()
    
    # Отправляем уведомление
    try:
        notify_embed = discord.Embed(
            title="❌ ВАС УДАЛИЛИ ИЗ СПИСКА VZП",
            color=discord.Color.red()
        )
        notify_embed.add_field(name="ID VZP", value=vzp_id, inline=False)
        notify_embed.add_field(name="Причина", value="Удалён администратором", inline=False)
        await member.send(embed=notify_embed)
    except:
        pass
    
    await interaction.response.send_message(
        f"✅ {member.mention} удалён из списка VZP `{vzp_id}`!",
        ephemeral=True
    )

@bot.tree.command(name="list_vzp", description="Показать активные VZP")
async def list_vzp(interaction: discord.Interaction):
    if not active_vzp:
        await interaction.response.send_message("📭 Нет активных VZP", ephemeral=True)
        return
    
    embed = discord.Embed(title="📋 АКТИВНЫЕ VZP", color=discord.Color.blue())
    
    for vzp_id, vzp_data in active_vzp.items():
        status = vzp_data.status
        status_emoji = {
            'OPEN': '🟢',
            'LIST IN PROCESS': '🟡',
            'VZP IN PROCESS': '🔵',
            'CLOSED': '🔴'
        }.get(status, '⚪')
        
        created_date = datetime.fromisoformat(vzp_data.created_at).strftime("%d.%m %H:%M")
        
        embed.add_field(
            name=f"**{vzp_id}** {status_emoji}",
            value=f"⏰ **Время:** {vzp_data.time}\n"
                  f"📅 **Создана:** {created_date}\n"
                  f"⚔️ **Тип:** {vzp_data.attack_def_name.split(' ')[1]}\n"
                  f"🎯 **Условия:** {', '.join(vzp_data.conditions_display)}\n"
                  f"🔫 **Калибры:** {' + '.join(vzp_data.caliber_names)}\n"
                  f"👥 **Участники:** {len(vzp_data.plus_users)}/{vzp_data.members}\n"
                  f"📊 **Статус:** {status}",
            inline=False
        )
    
    embed.set_footer(text=f"Всего активных VZP: {len(active_vzp)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Пингануть всех участников")
async def ping(interaction: discord.Interaction):
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
    
    await interaction.response.send_message("**РЕАКИ НА ТЕРРУ!**")
    
    for i in range(3):  # Уменьшил количество пингов
        await interaction.followup.send("@everyone")
        await asyncio.sleep(0.3)

@bot.tree.command(name="help_vzp", description="Помощь по командам VZP бота")
async def help_vzp(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 ПОМОЩЬ ПО КОМАНДАМ VZP БОТА",
        color=discord.Color.purple()
    )
    
    commands_list = [
        ("`/vzp_start`", "Создать новую VZP с условиями забива", "Требует админских прав"),
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
        embed.add_field(name=f"{cmd}", value=f"**Описание:** {desc}\n**Использование:** {example}", inline=False)
    
    embed.add_field(
        name="📊 СТАТУСЫ VZP",
        value="```\n🟢 OPEN - набор открыт\n🟡 LIST IN PROCESS - список формируется\n🔵 VZP IN PROCESS - VZP идёт\n🔴 CLOSED - VZP завершена\n```",
        inline=False
    )
    
    embed.add_field(
        name="⚙️ ТЕХНИЧЕСКИЕ ОГРАНИЧЕНИЯ",
        value=f"• Максимум активных VZP: **{MAX_ACTIVE_VZP}**\n• Максимум участников на VZP: **{MAX_PARTICIPANTS_PER_VZP}**\n• Кнопки работают после перезапуска\n• Данные сохраняются автоматически",
        inline=False
    )
    
    embed.set_footer(text="Бот разработан для стабильной работы с большим количеством участников")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="cleanup", description="Очистить старые данные (только для админов)")
async def cleanup(interaction: discord.Interaction):
    if not await has_high_role(interaction):
        await interaction.response.send_message("❌ У вас нет прав для этой команды!", ephemeral=True)
        return
    
    # Очищаем старые закрытые VZP (старше 7 дней)
    removed_count = 0
    current_time = datetime.now()
    
    vzp_ids_to_remove = []
    for vzp_id, vzp_info in closed_vzp.items():
        if 'closed_at' in vzp_info:
            try:
                closed_date = datetime.fromisoformat(vzp_info['closed_at'])
                if (current_time - closed_date).days > 7:
                    vzp_ids_to_remove.append(vzp_id)
            except:
                pass
    
    for vzp_id in vzp_ids_to_remove:
        del closed_vzp[vzp_id]
        removed_count += 1
    
    save_data()
    
    await interaction.response.send_message(
        f"✅ Очистка завершена!\n"
        f"🗑️ Удалено старых VZP: {removed_count}\n"
        f"📊 Активных VZP: {len(active_vzp)}\n"
        f"📁 Активных Views: {len(vzp_views)}",
        ephemeral=True
    )

# ===================== ЗАПУСК =====================
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'👑 ID бота: {bot.user.id}')
    print(f'📊 Серверов: {len(bot.guilds)}')
    print(f'📁 Активных VZP: {len(active_vzp)}')
    print(f'🎮 Активных Views: {len(vzp_views)}')
    print('=' * 50)
    print('Доступные команды:')
    print('   /vzp_start - создать VZP')
    print('   /start_vzp - запустить VZP')
    print('   /close_vzp - закрыть VZP')
    print('   /stop_reactions - остановить заявки')
    print('   /return_reactions - возобновить заявки')
    print('   /swap_player - заменить игрока')
    print('   /del_list - удалить из списка')
    print('   /ping - пингануть всех')
    print('   /list_vzp - список VZP')
    print('   /cleanup - очистка старых данных')
    print('   /help_vzp - помощь')
    print('=' * 50)
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(active_vzp)} активных VZP"
        )
    )

if __name__ == "__main__":
    print("🚀 Запуск бота VZP Manager...")
    print("📂 Загрузка сохраненных данных...")
    
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
        save_data()
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        save_data()