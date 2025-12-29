import bpy
import time

# =============================================================================
# 全局数据
# =============================================================================
# 结构: { "ObjName": { vert_idx: { "GroupName": weight } } }
XXMI_LOCK_DATA = {}       

# 结构: { "ObjName": "LAST_MODE" }
XXMI_MODE_TRACKER = {}    

# 忙碌状态锁
XXMI_IS_BUSY = False      

# =============================================================================
# 1. 批量还原逻辑 (核心)
# =============================================================================
def restore_weights_batch(obj_name):
    """
    针对单个物体执行批量还原。
    """
    global XXMI_LOCK_DATA
    
    # 安全检查
    if obj_name not in XXMI_LOCK_DATA: return
    obj = bpy.data.objects.get(obj_name)
    if not obj or obj.type != 'MESH': return

    locked_verts = XXMI_LOCK_DATA[obj_name]
    if not locked_verts: return

    mesh = obj.data
    vg_map = {vg.name: vg.index for vg in obj.vertex_groups}
    all_indices = list(locked_verts.keys())
    
    print(f"[XXMI] 正在还原 '{obj_name}' 的 {len(all_indices)} 个顶点权重...")
    
    # --- A. 批量移除 (极速) ---
    # 直接操作底层 C 结构，一次性移除
    for vg in obj.vertex_groups:
        vg.remove(all_indices)
        
    # --- B. 填回数据 ---
    # 仅处理依然存在的顶点和组
    for v_idx, saved_weights in locked_verts.items():
        if v_idx >= len(mesh.vertices): continue
            
        for vg_name, w in saved_weights.items():
            if vg_name in vg_map:
                obj.vertex_groups[vg_map[vg_name]].add([v_idx], w, 'REPLACE')
    
    # 强制刷新
    mesh.update()

# =============================================================================
# 2. 安全看门狗 (支持多物体独立监控)
# =============================================================================
def xxmi_multi_obj_watchdog():
    """
    每 0.5 秒巡逻一次。
    独立检查每一个被锁定物体的模式状态。
    """
    global XXMI_MODE_TRACKER, XXMI_LOCK_DATA, XXMI_IS_BUSY
    
    if XXMI_IS_BUSY: return 0.5
    if not XXMI_LOCK_DATA: return 1.0
    
    # 复制 key 列表以防遍历时修改字典
    monitor_list = list(XXMI_LOCK_DATA.keys())
    
    for obj_name in monitor_list:
        obj = bpy.data.objects.get(obj_name)
        
        # 物体丢失处理
        if not obj:
            del XXMI_LOCK_DATA[obj_name]
            if obj_name in XXMI_MODE_TRACKER: del XXMI_MODE_TRACKER[obj_name]
            continue
            
        current_mode = obj.mode
        last_mode = XXMI_MODE_TRACKER.get(obj_name, 'OBJECT')
        
        # --- 判定：该物体刚退出权重模式 ---
        # 注意：Blender 允许同时对多个物体进入/退出权重模式
        if last_mode == 'WEIGHT_PAINT' and current_mode != 'WEIGHT_PAINT':
            
            XXMI_IS_BUSY = True
            try:
                restore_weights_batch(obj_name)
            except Exception as e:
                print(f"[XXMI] 还原失败 {obj_name}: {e}")
            finally:
                XXMI_IS_BUSY = False
                
        # 更新该物体的状态
        XXMI_MODE_TRACKER[obj_name] = current_mode
        
    return 0.2

# =============================================================================
# 3. 锁定操作 (支持多物体选择)
# =============================================================================
class XXMI_OT_LockSelection(bpy.types.Operator):
    """锁定当前选中点 (支持多物体)"""
    bl_idname = "xxmi.lock_selection"
    bl_label = "锁定选中点"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global XXMI_LOCK_DATA, XXMI_MODE_TRACKER
        
        # 获取所有选中的网格物体 (不仅仅是激活的那个)
        targets = [o for o in context.selected_objects if o.type == 'MESH']
        
        if not targets:
            self.report({'ERROR'}, "请至少选择一个网格物体")
            return {'CANCELLED'}

        # 1. 强制切换所有物体到 OBJECT 模式以获取准确选区
        original_mode = context.object.mode if context.object else 'OBJECT'
        if original_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        total_locked = 0
        objects_processed = 0

        # 2. 遍历每一个选中的物体
        for obj in targets:
            if obj.name not in XXMI_LOCK_DATA:
                XXMI_LOCK_DATA[obj.name] = {}
                
            mesh = obj.data
            vg_index_map = {vg.index: vg.name for vg in obj.vertex_groups}
            
            count_obj = 0
            
            # 扫描该物体的顶点
            selected_verts = [v for v in mesh.vertices if v.select]
            
            if not selected_verts:
                continue
                
            for v in selected_verts:
                w_record = {}
                for g in v.groups:
                    if g.group in vg_index_map:
                        vg_name = vg_index_map[g.group]
                        w_record[vg_name] = g.weight
                
                XXMI_LOCK_DATA[obj.name][v.index] = w_record
                count_obj += 1
            
            if count_obj > 0:
                print(f"[XXMI] 已锁定 {count_obj} 个顶点 (物体: '{obj.name}')")
                XXMI_MODE_TRACKER[obj.name] = 'OBJECT'
                total_locked += count_obj
                objects_processed += 1

        # 3. 恢复之前的模式
        if original_mode != 'OBJECT':
            try:
                if context.view_layer.objects.active in targets:
                    bpy.ops.object.mode_set(mode=original_mode)
                    for obj in targets:
                        XXMI_MODE_TRACKER[obj.name] = original_mode
            except:
                pass
        
        # 4. 确保 Timer 启动
        if not bpy.app.timers.is_registered(xxmi_multi_obj_watchdog):
            bpy.app.timers.register(xxmi_multi_obj_watchdog, persistent=True)

        if objects_processed > 0:
            msg = f"已锁定 {total_locked} 个顶点 (共 {objects_processed} 个物体)。"
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "未在选中的物体上找到被选中的顶点。")
            return {'CANCELLED'}

class XXMI_OT_UnlockAll(bpy.types.Operator):
    """清空所有"""
    bl_idname = "xxmi.unlock_all"
    bl_label = "清空所有锁定"
    
    def execute(self, context):
        global XXMI_LOCK_DATA
        XXMI_LOCK_DATA.clear()
        self.report({'INFO'}, "所有锁定已清空。")
        return {'FINISHED'}

class XXMI_OT_SelectLocked(bpy.types.Operator):
    """选中锁定点 (支持多物体)"""
    bl_idname = "xxmi.select_locked"
    bl_label = "选中已锁定点"
    
    def execute(self, context):
        global XXMI_LOCK_DATA
        
        # 获取所有有记录的物体
        targets = [bpy.data.objects.get(name) for name in XXMI_LOCK_DATA.keys()]
        targets = [t for t in targets if t] # 过滤空值
        
        if not targets: return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        
        # 遍历处理
        for obj in targets:
            obj.select_set(True)
            mesh = obj.data
            for v in mesh.vertices: v.select = False
            
            for idx in XXMI_LOCK_DATA[obj.name]:
                if idx < len(mesh.vertices):
                    mesh.vertices[idx].select = True
        
        # 将所有涉及的物体切入编辑模式 (多物体编辑)
        if targets:
            context.view_layer.objects.active = targets[0]
            bpy.ops.object.mode_set(mode='EDIT')
            
        return {'FINISHED'}

# =============================================================================
# 4. UI 面板
# =============================================================================
class XXMI_PT_LockerPanel(bpy.types.Panel):
    bl_label = "锁定选中顶点权重"
    bl_idname = "XXMI_PT_LockerPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XXMI Tools"
    bl_order = 105

    def draw(self, context):
        layout = self.layout
        global XXMI_LOCK_DATA
        
        total_objs = len(XXMI_LOCK_DATA)
        total_verts = sum(len(v) for v in XXMI_LOCK_DATA.values())
            
        box = layout.box()
        row = box.row()
        if total_verts > 0:
            # 状态显示：保护中: 123 点 (共 2 物体)
            row.label(text=f"保护中: {total_verts} 点 (共 {total_objs} 物体)", icon='LOCKED')
        else:
            row.label(text="无锁定数据", icon='UNLOCKED')
            
        col = box.column(align=True)
        col.operator("xxmi.lock_selection", text="锁定选中点", icon='ADD')
        
        if total_verts > 0:
            col.separator()
            row = col.row(align=True)
            row.operator("xxmi.select_locked", text="选择已锁定", icon='RESTRICT_SELECT_OFF')
            row.operator("xxmi.unlock_all", text="清空/解锁全部", icon='TRASH')
            box.label(text="退出权重模式时自动还原", icon='INFO')

# =============================================================================
# 注册
# =============================================================================
def register():
    # 注意：Operator 和 Panel 类由 auto_load.py 自动注册
    # 我们只负责注册 Timer
    if not bpy.app.timers.is_registered(xxmi_multi_obj_watchdog):
        bpy.app.timers.register(xxmi_multi_obj_watchdog, persistent=True)

def unregister():
    if bpy.app.timers.is_registered(xxmi_multi_obj_watchdog):
        bpy.app.timers.unregister(xxmi_multi_obj_watchdog)