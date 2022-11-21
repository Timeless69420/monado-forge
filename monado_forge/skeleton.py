import bpy
import math
import mathutils
import os
import traceback
from bpy.props import (
						BoolProperty,
						EnumProperty,
						FloatProperty,
						PointerProperty,
						StringProperty,
						)
from bpy.types import (
						Operator,
						Panel,
						PropertyGroup,
						)

from . utils import *

class XBSkeletonImportOperator(Operator):
	bl_idname = "object.xb_tools_skeleton_operator"
	bl_label = "Xenoblade Skeleton Import Operator"
	bl_description = "Imports a skeleton from a Xenoblade file"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		return context.scene.xb_tools_skeleton.path
	
	def execute(self, context):
		try:
			game = context.scene.xb_tools.game
			absolutePath = bpy.path.abspath(context.scene.xb_tools_skeleton.path)
			boneSize = context.scene.xb_tools_skeleton.boneSize
			positionEpsilon = context.scene.xb_tools_skeleton.positionEpsilon
			angleEpsilon = context.scene.xb_tools_skeleton.angleEpsilon
			importEndpoints = context.scene.xb_tools_skeleton.importEndpoints
			print("Importing skeleton from: "+absolutePath)
			
			filename, fileExtension = os.path.splitext(absolutePath)
			expectedExtension = {"XC1":".brres","XCX":".xcx","XC2":".arc","XC1DE":".chr","XC3":".chr",}[game]
			if fileExtension != expectedExtension:
				self.report({"ERROR"}, "Unexpected file type (for "+game+", expected "+expectedExtension+")")
				return {"CANCELLED"}
			
			# first, read in the data and store it in a game-agnostic way
			if game == "XC1":
				modelFormat = "BRES"
				endian = "big"
			elif game == "XCX":
				modelFormat = "[xcx]"
				endian = "big"
			elif game == "XC2":
				modelFormat = "SAR1"
				endian = "little"
			elif game == "XC1DE":
				modelFormat = "SAR1"
				endian = "little"
			elif game == "XC3":
				modelFormat = "SAR1"
				endian = "little"
			
			importedSkeletons = []
			with open(absolutePath, "rb") as f:
				if modelFormat == "BRES":
					self.report({"ERROR"}, ".brres format not yet supported")
					return {"CANCELLED"}
				elif modelFormat == ".xcx":
					self.report({"ERROR"}, "(whatever XCX uses) format not yet supported")
					return {"CANCELLED"}
				elif modelFormat == "SAR1":
					magic = f.read(4)
					if magic != b"1RAS":
						self.report({"ERROR"}, "Not a valid "+expectedExtension+" file (unexpected header)")
						return {"CANCELLED"}
					fileSize = readAndParseInt(f,4,endian)
					version = readAndParseInt(f,4,endian)
					numFiles = readAndParseInt(f,4,endian)
					tocOffset = readAndParseInt(f,4,endian)
					dataOffset = readAndParseInt(f,4,endian)
					unknown1 = readAndParseInt(f,4,endian)
					unknown2 = readAndParseInt(f,4,endian)
					path = readStr(f)
					
					for i in range(numFiles):
						f.seek(tocOffset+i*0x40)
						offset = readAndParseInt(f,4,endian)
						size = readAndParseInt(f,4,endian)
						unknown = readAndParseInt(f,4,endian)
						filename = readStr(f)
						# todo: try to do this based on file type instead of name
						if game == "XC3":
							skelFilename = "skeleton"
						else: # XC2, XC1DE
							skelFilename = ".skl"
						if skelFilename not in filename: # yes, we're just dropping everything that's not a skeleton, this ain't a general-purpose script
							continue
						
						f.seek(offset)
						bcMagic = f.read(4)
						if bcMagic == b"LCHC": # some sort of special case I guess? (seen in XBC2ModelDecomp)
							continue
						if bcMagic != b"BC\x00\x00": # BC check
							self.report({"ERROR"}, "BC check failed for "+filename+" (dunno what this means tbh, file probably bad in some way e.g. wrong endianness)")
							continue
						blockCount = readAndParseInt(f,4,endian)
						fileSize = readAndParseInt(f,4,endian)
						pointerCount = readAndParseInt(f,4,endian)
						dataOffset = readAndParseInt(f,4,endian)
						
						f.seek(offset+dataOffset+4)
						skelMagic = f.read(4)
						if skelMagic != b"SKEL":
							self.report({"ERROR"}, ".skl file "+filename+" has bad header")
							return {"CANCELLED"}
						
						skelHeaderUnknown1 = readAndParseInt(f,4,endian)
						skelHeaderUnknown2 = readAndParseInt(f,4,endian)
						skelTocItems = []
						for j in range(10): # yeah it's a magic number, deal with it
							itemOffset = readAndParseInt(f,4,endian)
							itemUnknown1 = readAndParseInt(f,4,endian)
							itemCount = readAndParseInt(f,4,endian)
							itemUnknown2 = readAndParseInt(f,4,endian)
							skelTocItems.append([itemOffset,itemUnknown1,itemCount,itemUnknown2])
						
						# finally we have the datums
						# TOC layout:
						# [0]: ???
						# [1]: ???
						# [2]: bone parent IDs
						# [3]: bone names
						# [4]: bone data (posititon, rotation, scale)
						# [5]: ???
						# [6]: endpoint parent IDs
						# [7]: endpoint names
						# [8]: endpoint data (position, rotation, scale)
						# [9]: ???
						if (skelTocItems[2][2] != skelTocItems[3][2]) or (skelTocItems[3][2] != skelTocItems[4][2]):
							print("bone parent entries: "+str(skelTocItems[2][2]))
							print("bone name entries: "+str(skelTocItems[3][2]))
							print("bone data entries: "+str(skelTocItems[4][2]))
							self.report({"ERROR"}, ".skl file "+filename+" has inconsistent bone counts (see console)")
							return {"CANCELLED"}
						if importEndpoints:
							if (skelTocItems[6][2] != skelTocItems[7][2]) or (skelTocItems[7][2] != skelTocItems[8][2]):
								print("endpoint parent entries: "+str(skelTocItems[6][2]))
								print("endpoint name entries: "+str(skelTocItems[7][2]))
								print("endpoint data entries: "+str(skelTocItems[8][2]))
								self.report({"WARNING"}, ".skl file "+filename+" has inconsistent endpoint counts (see console); endpoint import skipped")
						forgeBones = []
						for b in range(skelTocItems[2][2]):
							# parent
							f.seek(offset+skelTocItems[2][0]+b*2)
							parent = readAndParseInt(f,2,endian)
							# name
							f.seek(offset+skelTocItems[3][0]+b*16)
							nameOffset = readAndParseInt(f,4,endian)
							f.seek(offset+nameOffset)
							name = readStr(f)
							# data
							f.seek(offset+skelTocItems[4][0]+b*(4*12))
							px = readAndParseFloat(f,endian)
							py = readAndParseFloat(f,endian)
							pz = readAndParseFloat(f,endian)
							pw = readAndParseFloat(f,endian)
							rx = readAndParseFloat(f,endian)
							ry = readAndParseFloat(f,endian)
							rz = readAndParseFloat(f,endian)
							rw = readAndParseFloat(f,endian)
							sx = readAndParseFloat(f,endian)
							sy = readAndParseFloat(f,endian)
							sz = readAndParseFloat(f,endian)
							sw = readAndParseFloat(f,endian)
							# reminder that the pos and scale are x,y,z,w but the rotation is w,x,y,z
							fb = MonadoForgeBone()
							fb.setParent(parent)
							fb.setName(name)
							fb.setPos([px,py,pz,pw])
							fb.setRot([rw,rx,ry,rz])
							fb.setScl([sx,sy,sz,sw])
							fb.setEndpoint(False)
							forgeBones.append(fb)
						if importEndpoints:
							for ep in range(skelTocItems[6][2]):
								# parent
								f.seek(offset+skelTocItems[6][0]+ep*2)
								parent = readAndParseInt(f,2,endian)
								# name
								f.seek(offset+skelTocItems[7][0]+ep*8) # yeah endpoint names are packed tighter than "normal" bone names
								nameOffset = readAndParseInt(f,4,endian)
								f.seek(offset+nameOffset)
								name = readStr(f)
								# data
								f.seek(offset+skelTocItems[8][0]+ep*(4*12))
								px = readAndParseFloat(f,endian)
								py = readAndParseFloat(f,endian)
								pz = readAndParseFloat(f,endian)
								pw = readAndParseFloat(f,endian)
								rx = readAndParseFloat(f,endian)
								ry = readAndParseFloat(f,endian)
								rz = readAndParseFloat(f,endian)
								rw = readAndParseFloat(f,endian)
								sx = readAndParseFloat(f,endian)
								sy = readAndParseFloat(f,endian)
								sz = readAndParseFloat(f,endian)
								sw = readAndParseFloat(f,endian)
								# for some reason, endpoints tend to have pw = 0, which positions it relative to root instead of parent (and we don't want that)
								if pw == 0.0: pw = 1.0
								# reminder that the pos and scale are x,y,z,w but the rotation is w,x,y,z
								fb = MonadoForgeBone()
								fb.setParent(parent)
								fb.setName(name)
								fb.setPos([px,py,pz,pw])
								fb.setRot([rw,rx,ry,rz])
								fb.setScl([sx,sy,sz,sw])
								fb.setEndpoint(True)
								forgeBones.append(fb)
						importedSkeletons.append(forgeBones)
					if not importedSkeletons:
						self.report({"ERROR"}, "No valid .skl items found in file")
						return {"CANCELLED"}
				else:
					self.report({"ERROR"}, "Unknown format: "+modelFormat)
					return {"CANCELLED"}
			
			# we now have the skeletons in generic format - create the armatures
			for s in importedSkeletons:
				bpy.ops.object.select_all(action="DESELECT")
				bpy.ops.object.armature_add(enter_editmode=True, align="WORLD", location=(0,0,0), rotation=(0,0,0), scale=(1,1,1))
				skeleton = bpy.context.view_layer.objects.active.data
				skeleton.show_names = True
				# delete the default bone to start with
				bpy.ops.armature.select_all(action="SELECT")
				bpy.ops.armature.delete()
				# start adding
				editBones = skeleton.edit_bones
				for b in s:
					# assumption: no bone will ever precede its parent (i.e. the parent will always be there already to attach to, no second pass needed)
					#boneParent,boneName,bonePos,boneRot,boneScl,boneIsEndpoint = b[0],b[1],b[2],b[3],b[4],b[5]
					newBone = editBones.new(b.getName())
					newBone.length = boneSize
					newBone.parent = editBones[b.getParent()] if b.getParent() != 0xffff else None
					parentMatrix = newBone.parent.matrix if newBone.parent else mathutils.Matrix.Identity(4)
					posMatrix = mathutils.Matrix.Translation(b.getPos())
					rotMatrix = mathutils.Quaternion(b.getRot()).to_matrix()
					rotMatrix.resize_4x4()
					newBone.matrix = parentMatrix @ (posMatrix @ rotMatrix)
					newBone.length = boneSize # have seen odd non-rounding when not doing this
					# put "normal" bones in layer 1 and endpoints in layer 2
					# must be done in this order or the [0] set will be dropped because bones must be in at least one layer
					newBone.layers[1] = b.isEndpoint()
					newBone.layers[0] = not b.isEndpoint()
				# now that the bones are in, spin them around so they point in a more logical-for-Blender direction
				for b in editBones:
					b.transform(mathutils.Euler((math.radians(90),0,0)).to_matrix()) # transform from lying down (+Y up +Z forward) to standing up (+Z up -Y forward)
					roll = b.y_axis # roll gets lost after the following matrix mult for some reason, so preserve it
					b.matrix = b.matrix @ mathutils.Matrix([[0,1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1]]) # change from +X being the "main axis" to +Y
					b.align_roll(roll)
					# everything done, now apply epsilons
					b.head = [(0 if abs(p) < positionEpsilon else p) for p in b.head]
					b.tail = [(0 if abs(p) < positionEpsilon else p) for p in b.tail]
					clampBoneRoll(b,angleEpsilon)
				# cleanup
				armatureName = editBones[0].name
				if armatureName.endswith("_top"):
					armatureName = armatureName[:-4]
				if armatureName.endswith("_Bone"):
					armatureName = armatureName[:-5]
				bpy.context.view_layer.objects.active.name = armatureName
				bpy.context.view_layer.objects.active.data.name = armatureName
				bpy.ops.armature.select_all(action="DESELECT")
				bpy.ops.object.mode_set(mode="OBJECT")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonBoneFlipAllOperator(Operator):
	bl_idname = "object.xb_skeleton_boneflip_all_operator"
	bl_label = "Xenoblade Skeleton Bone Flip All Operator"
	bl_description = "Flips all _R bones, pointing them the other way (reversible)"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		activeObject = context.view_layer.objects.active
		if not activeObject: return False
		if activeObject.type != "ARMATURE": return False
		if activeObject.mode == "POSE": return False
		return True
	
	def execute(self, context):
		try:
			nonFinalMirror = context.scene.xb_tools_skeleton.nonFinalMirror
			angleEpsilon = context.scene.xb_tools_skeleton.angleEpsilon
			skeleton = bpy.context.view_layer.objects.active.data
			bpy.ops.object.mode_set(mode="EDIT")
			editBones = skeleton.edit_bones
			flipCount = 0
			for bone in editBones:
				if bone.name.endswith("_R") or (nonFinalMirror and "_R_" in bone.name):
					roll = bone.roll
					bone.matrix = bone.matrix @ mathutils.Matrix([[-1,0,0,0],[0,-1,0,0],[0,0,-1,0],[0,0,0,1]])
					bone.roll = flipRoll(roll)
					clampBoneRoll(bone,angleEpsilon)
					flipCount += 1
			bpy.ops.object.mode_set(mode="OBJECT")
			self.report({"INFO"}, "Flipped "+str(flipCount)+" bones.")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonBoneFlipSelectedOperator(Operator):
	bl_idname = "object.xb_skeleton_boneflip_selected_operator"
	bl_label = "Xenoblade Skeleton Bone Flip Selected Operator"
	bl_description = "Flips all selected bones, pointing them the other way (reversible)"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		activeObject = context.view_layer.objects.active
		if not activeObject: return False
		if activeObject.type != "ARMATURE": return False
		if activeObject.mode != "EDIT": return False
		return True
	
	def execute(self, context):
		try:
			angleEpsilon = context.scene.xb_tools_skeleton.angleEpsilon
			for bone in bpy.context.selected_bones:
				roll = bone.roll
				bone.matrix = bone.matrix @ mathutils.Matrix([[-1,0,0,0],[0,-1,0,0],[0,0,-1,0],[0,0,0,1]])
				bone.roll = flipRoll(roll)
				clampBoneRoll(bone,angleEpsilon)
			self.report({"INFO"}, "Flipped "+str(len(bpy.context.selected_bones))+" bones.")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonBoneMirrorAutoOperator(Operator):
	bl_idname = "object.xb_skeleton_bonemirror_auto_operator"
	bl_label = "Xenoblade Skeleton Bone Mirror Auto Operator"
	bl_description = "Edits all _R bones to mirror the _L bones of the same name (destructive)"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		activeObject = context.view_layer.objects.active
		if not activeObject: return False
		if activeObject.type != "ARMATURE": return False
		if activeObject.mode == "POSE": return False
		return True
	
	def execute(self, context):
		try:
			nonFinalMirror = context.scene.xb_tools_skeleton.nonFinalMirror
			positionEpsilon = context.scene.xb_tools_skeleton.positionEpsilon
			angleEpsilon = context.scene.xb_tools_skeleton.angleEpsilon
			skeleton = bpy.context.view_layer.objects.active.data
			bpy.ops.object.mode_set(mode="EDIT")
			editBones = skeleton.edit_bones
			mirroredCount = 0
			outOfRangeCount = 0
			for bone in editBones:
				if bone.name.endswith("_R") or (nonFinalMirror and "_R_" in bone.name):
					mirrorName = ""
					otherBone = None
					if "_R" in bone.name: mirrorName = bone.name.replace("_R","_L")
					if "_L" in bone.name: mirrorName = bone.name.replace("_L","_R")
					try:
						otherBone = editBones[mirrorName]
					except KeyError:
						otherBone = None
					if otherBone:
						canAutoMirror,message = isBonePairAutoMirrorable(bone,otherBone,positionEpsilon,angleEpsilon)
						if canAutoMirror:
							mirrorBone(bone,otherBone)
							mirroredCount += 1
						else:
							print(bone.name+" != "+otherBone.name+" ~ "+message)
							outOfRangeCount += 1
			bpy.ops.object.mode_set(mode="OBJECT")
			if outOfRangeCount > 0:
				self.report({"WARNING"}, "Mirrored "+str(mirroredCount)+" bones but skipped "+str(outOfRangeCount)+" for being out of epsilon tolerance. See console for list.")
			else:
				self.report({"INFO"}, "Mirrored "+str(mirroredCount)+" bones.")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonBoneMirrorSelectedOperator(Operator):
	bl_idname = "object.xb_skeleton_bonemirror_selected_operator"
	bl_label = "Xenoblade Skeleton Bone Mirror Selected Operator"
	bl_description = "Edits all selected bones to mirror the bones of the same name with reverse L/R polarity (destructive)"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		activeObject = context.view_layer.objects.active
		if not activeObject: return False
		if activeObject.type != "ARMATURE": return False
		if activeObject.mode != "EDIT": return False
		return True
	
	def execute(self, context):
		try:
			positionEpsilon = context.scene.xb_tools_skeleton.positionEpsilon
			angleEpsilon = context.scene.xb_tools_skeleton.angleEpsilon
			# edit mode is assumed (panel is edit mode limited)
			skeleton = bpy.context.view_layer.objects.active.data
			editBones = skeleton.edit_bones
			mirroredCount = 0
			outOfRangeCount = 0
			for bone in bpy.context.selected_bones:
				mirrorName = ""
				otherBone = None
				if "_R" in bone.name: mirrorName = bone.name.replace("_R","_L")
				if "_L" in bone.name: mirrorName = bone.name.replace("_L","_R")
				try:
					otherBone = editBones[mirrorName]
				except KeyError:
					otherBone = None
				if otherBone:
					canAutoMirror,message = isBonePairAutoMirrorable(bone,otherBone,positionEpsilon,angleEpsilon)
					if not canAutoMirror:
						print(bone.name+" != "+otherBone.name+" ~ "+message)
						outOfRangeCount += 1
					# but since the user selected this bone on purpose, we mirror it anyway
					mirrorBone(bone,otherBone)
					mirroredCount += 1
			if mirroredCount < len(bpy.context.selected_bones):
				self.report({"WARNING"}, "Did not mirror "+str(len(bpy.context.selected_bones)-mirroredCount)+" bones (no matching name on the other side).")
			if outOfRangeCount > 0:
				self.report({"WARNING"}, str(outOfRangeCount)+" bones were out of epsilon tolerance, but were mirrored anyway. See console for list.")
			else:
				self.report({"INFO"}, "Mirrored "+str(mirroredCount)+" bones.")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonNonFinalLRFixAllOperator(Operator):
	bl_idname = "object.xb_skeleton_nonfinallrfix_all_operator"
	bl_label = "Xenoblade Skeleton Non Final LR Fix All Operator"
	bl_description = "Edits all bone names to put the _L/_R at the end"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		activeObject = context.view_layer.objects.active
		if not activeObject: return False
		if activeObject.type != "ARMATURE": return False
		if activeObject.mode == "POSE": return False
		return True
	
	def execute(self, context):
		try:
			skeleton = bpy.context.view_layer.objects.active.data
			bpy.ops.object.mode_set(mode="EDIT")
			editBones = skeleton.edit_bones
			count = 0
			for bone in editBones:
				# assumption: no bone can have both _L_ and _R_
				if "_L_" in bone.name:
					bone.name = bone.name.replace("_L_","_") + "_L"
					count += 1
				if "_R_" in bone.name:
					bone.name = bone.name.replace("_R_","_") + "_R"
					count += 1
			bpy.ops.object.mode_set(mode="OBJECT")
			self.report({"INFO"}, "Renamed "+str(count)+" bones.")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonNonFinalLRFixSelectedOperator(Operator):
	bl_idname = "object.xb_skeleton_nonfinallrfix_selected_operator"
	bl_label = "Xenoblade Skeleton Non Final LR Fix Selected Operator"
	bl_description = "Edits selected bone names to put the _L/_R at the end"
	bl_options = {"REGISTER","UNDO"}
	
	@classmethod
	def poll(cls, context):
		activeObject = context.view_layer.objects.active
		if not activeObject: return False
		if activeObject.type != "ARMATURE": return False
		if activeObject.mode != "EDIT": return False
		return True
	
	def execute(self, context):
		try:
			# edit mode is assumed (panel is edit mode limited)
			skeleton = bpy.context.view_layer.objects.active.data
			editBones = skeleton.edit_bones
			count = 0
			for bone in bpy.context.selected_bones:
				# assumption: no bone can have both _L_ and _R_
				if "_L_" in bone.name:
					bone.name = bone.name.replace("_L_","_") + "_L"
					count += 1
				if "_R_" in bone.name:
					bone.name = bone.name.replace("_R_","_") + "_R"
					count += 1
			self.report({"INFO"}, "Renamed "+str(count)+" bones.")
		except Exception:
			traceback.print_exc()
			self.report({"ERROR"}, "Unexpected error; see console")
			return {"CANCELLED"}
		return {"FINISHED"}

class XBSkeletonToolsProperties(PropertyGroup):
	path : StringProperty(
		name="Path",
		description="File to import",
		default="",
		maxlen=1024,
		subtype="FILE_PATH",
	)
	boneSize : FloatProperty(
		name="Bone Size",
		description="Length of bones",
		default=0.1,
		min=0.01,
		soft_min=0.01,
		soft_max=10,
		unit="LENGTH",
	)
	positionEpsilon : FloatProperty(
		name="Position Epsilon",
		description="Positions less than this are set to zero; positions within this are considered equal for auto-mirroring",
		default=0.0001, # 1 micrometer
		min=0,
		max=0.001, # 1 milimeter - we're working on human scales, 1mm is significant no matter what
		soft_min=0,
		soft_max=0.001,
		unit="LENGTH",
	)
	angleEpsilon : FloatProperty(
		name="Angle Epsilon",
		description="Angles less than this are set to zero; angles within this are considered equal for auto-mirroring",
		default=math.radians(0.1),
		min=0,
		max=math.radians(1), # 1 degree is significant no matter how you look at it
		soft_min=0,
		soft_max=1,
		step=1,
		unit="ROTATION",
	)
	nonFinalMirror : BoolProperty(
		name="Accept Non-Final L/R",
		description="Treat non-final _L_ and _R_ in bone names as being mirrored",
		default=True,
	)
	importEndpoints : BoolProperty(
		name="Also Import Endpoints",
		description="Imports endpoints as well and adds them to the skeleton (in layer 2)",
		default=False,
	)

class OBJECT_PT_XBSkeletonToolsPanel(Panel):
	bl_idname = "OBJECT_PT_XBSkeletonToolsPanel"
	bl_label = "Skeleton"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_parent_id = "OBJECT_PT_XBToolsPanel"

	def draw(self, context):
		layout = self.layout
		scn = context.scene
		activeObject = bpy.context.view_layer.objects.active
		col = layout.column(align=True)
		settingsPanel = col.column(align=True)
		settingsPanel.prop(scn.xb_tools_skeleton, "positionEpsilon")
		settingsPanel.prop(scn.xb_tools_skeleton, "angleEpsilon")
		settingsPanel.prop(scn.xb_tools_skeleton, "nonFinalMirror")
		col.separator(factor=2)
		importPanel = col.column(align=True)
		importPanel.label(text="Import")
		importPanel.prop(scn.xb_tools_skeleton, "path", text="")
		importPanel.prop(scn.xb_tools_skeleton, "boneSize")
		epSubcol = importPanel.column()
		epSubcol.prop(scn.xb_tools_skeleton, "importEndpoints")
		if (scn.xb_tools.game == "XC1"):
			epSubcol.enabled = False
		importPanel.separator()
		importPanel.operator(XBSkeletonImportOperator.bl_idname, text="Import Skeleton", icon="IMPORT")
		col.separator(factor=2)
		modifyPanel = col.column(align=True)
		if activeObject and activeObject.mode == "EDIT":
			modifyPanel.label(text="Modify Selected")
			modifyPanel.operator(XBSkeletonBoneFlipSelectedOperator.bl_idname, text="Flip _R Bones", icon="ARROW_LEFTRIGHT")
			modifyPanel.operator(XBSkeletonBoneMirrorSelectedOperator.bl_idname, text="Mirror _R Bones", icon="MOD_MIRROR")
			modifyPanel.operator(XBSkeletonNonFinalLRFixSelectedOperator.bl_idname, text="Fix Non-Final L/R Bone Names")
		else:
			modifyPanel.label(text="Modify")
			modifyPanel.operator(XBSkeletonBoneFlipAllOperator.bl_idname, text="Flip _R Bones", icon="ARROW_LEFTRIGHT")
			modifyPanel.operator(XBSkeletonBoneMirrorAutoOperator.bl_idname, text="Mirror _R Bones", icon="MOD_MIRROR")
			modifyPanel.operator(XBSkeletonNonFinalLRFixAllOperator.bl_idname, text="Fix Non-Final L/R Bone Names")

classes = (
			XBSkeletonImportOperator,
			XBSkeletonBoneFlipAllOperator,
			XBSkeletonBoneFlipSelectedOperator,
			XBSkeletonBoneMirrorAutoOperator,
			XBSkeletonBoneMirrorSelectedOperator,
			XBSkeletonNonFinalLRFixAllOperator,
			XBSkeletonNonFinalLRFixSelectedOperator,
			XBSkeletonToolsProperties,
			OBJECT_PT_XBSkeletonToolsPanel,
			)

def register():
	from bpy.utils import register_class
	for cls in classes:
		register_class(cls)

	bpy.types.Scene.xb_tools_skeleton = PointerProperty(type=XBSkeletonToolsProperties)

def unregister():
	from bpy.utils import unregister_class
	for cls in reversed(classes):
		unregister_class(cls)
	del bpy.types.Scene.xb_tools_skeleton

#[...]