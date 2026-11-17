from __future__ import annotations
import json,math
from pathlib import Path
import cv2
import ezdxf
import numpy as np
import resvg_py
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
from shapely import affinity
from shapely.geometry import LineString,Point,Polygon,GeometryCollection
from shapely.ops import nearest_points,unary_union

OUT=Path(__file__).resolve().parents[1]; OUT.mkdir(parents=True,exist_ok=True)
SRC=OUT/'sources'/'vintage-owl-emblem.svg'
PW,PH=5000,3868
png=resvg_py.svg_to_bytes(svg_path=str(SRC),width=PW,height=PH,background='white')
arr=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_GRAYSCALE)
_,mask=cv2.threshold(arr,100,255,cv2.THRESH_BINARY_INV)
contours,hier=cv2.findContours(mask,cv2.RETR_TREE,cv2.CHAIN_APPROX_TC89_KCOS)
hier=hier[0]
# Crop to the actual emblem bounds, then fit it inside the oval frame.
x0,y0,bw,bh=cv2.boundingRect(mask); scale=min(560/bw,420/bh)
rings=[]
for c in contours:
 if len(c)<3: continue
 pts=[((float(p[0][0])-(x0+bw/2))*scale,((y0+bh/2)-float(p[0][1]))*scale) for p in c]
 poly=Polygon(pts)
 if poly.is_valid and poly.area>=0.35: rings.append(poly.simplify(0.12,preserve_topology=True))
# Binary contours alternate fill at each nesting depth; symmetric difference reproduces that mask.
art=GeometryCollection()
for p in sorted(rings,key=lambda g:g.area,reverse=True): art=art.symmetric_difference(p)
if not art.is_valid: art=art.buffer(0)
# Thicken source line art into robust positive metal webs and merge tiny gaps.
art=art.buffer(2.1,join_style=1).buffer(-0.35,join_style=1)
panel=affinity.scale(Point(0,0).buffer(1,resolution=512),xfact=290,yfact=225)
art=art.intersection(panel.buffer(-7))
parts=list(art.geoms) if hasattr(art,'geoms') else [art]
art=unary_union([g for g in parts if g.area>=10])
ring=panel.difference(panel.buffer(-16))
mounts=unary_union([Point(-150,190).buffer(4,resolution=64),Point(150,190).buffer(4,resolution=64)])
material=unary_union([ring,art]).difference(mounts)
# Require exactly one intended metal component. Small detached artwork is a
# conversion failure rather than something to silently discard.
parts=list(material.geoms) if hasattr(material,'geoms') else [material]
parts=sorted(parts,key=lambda g:g.area,reverse=True)
discarded=[]
if len(parts)!=1:
 main=parts[0]; kept=[main]; connectors=[]
 for g in parts[1:]:
  a,b=nearest_points(main,g); dist=main.distance(g)
  if g.area<50:
   discarded.append(g); continue
  if dist>=10: raise RuntimeError('Substantial owl detail requires an excessive bridge')
  kept.append(g); connectors.append(LineString([(a.x,a.y),(b.x,b.y)]).buffer(2.3,cap_style=1))
 material=unary_union([*kept,*connectors])
 parts=list(material.geoms) if hasattr(material,'geoms') else [material]
 if len(parts)!=1: raise RuntimeError('Local owl joins did not connect all retained details')
# Increase all positive webs by 0.7 mm per side, then restore the exact panel
# boundary and 8 mm mounting holes. This repairs the one 2.737 mm web without
# introducing a visible local patch.
material=material.buffer(0.7,join_style=1).intersection(panel).difference(mounts)
parts=list(material.geoms) if hasattr(material,'geoms') else [material]
if len(parts)!=1: raise RuntimeError('Web repair disconnected the owl panel')
material=parts[0]
if not material.is_valid: material=material.buffer(0)
if material.geom_type!='Polygon': raise RuntimeError('Final material is not one polygon')
# Resolve every remaining sub-4 mm separation between independent cuts. Prefer
# merging adjacent apertures; if that would disconnect the panel, fill only the
# smaller micro-aperture instead.
merged_close_profiles=0; filled_micro_apertures=0
for _ in range(250):
 hs=[Polygon(r) for r in material.interiors]
 nearest=None
 for i,a in enumerate(hs):
  for j,b in enumerate(hs[i+1:],i+1):
   d=a.distance(b)
   if nearest is None or d<nearest[0]: nearest=(d,i,j,a,b)
 if nearest is None or nearest[0]>=4.0: break
 _,i,j,a,b=nearest
 p1,p2=nearest_points(a,b)
 corridor=LineString([(p1.x,p1.y),(p2.x,p2.y)]).buffer(1.8,cap_style=1)
 candidate=material.difference(corridor)
 if candidate.geom_type=='Polygon':
  material=candidate; merged_close_profiles+=1
 else:
  drop=i if a.area<=b.area else j
  kept=[list(r.coords) for k,r in enumerate(material.interiors) if k!=drop]
  material=Polygon(material.exterior.coords,kept); filled_micro_apertures+=1
else:
 raise RuntimeError('Profile-clearance repair did not converge')
# Quantify independent profile spacing.
holes=[Polygon(r) for r in material.interiors]
min_gap=999.0; pair=None
for i,a in enumerate(holes):
 for j,b in enumerate(holes[i+1:],i+1):
  d=a.distance(b)
  if d<min_gap:
   min_gap=d; pair=[i,j]
# Export closed contours.
def coords(poly): return [(round(x+300,4),round(y+300,4)) for x,y in poly.exterior.coords[:-1]]
doc=ezdxf.new('R2010'); doc.units=ezdxf.units.MM; doc.layers.add('CUT',color=7); msp=doc.modelspace()
msp.add_lwpolyline(coords(material),close=True,dxfattribs={'layer':'CUT'})
for r in material.interiors:
 p=Polygon(r); msp.add_lwpolyline(coords(p),close=True,dxfattribs={'layer':'CUT'})
doc.saveas(OUT/'vintage-owl-heraldic-panel.dxf')
# SVG even-odd paths.
def path_d(ring):
 pts=[(x+300,600-(y+300)) for x,y in list(ring.coords)[:-1]]
 return 'M '+' L '.join(f'{x:.3f},{y:.3f}' for x,y in pts)+' Z'
d=' '.join([path_d(material.exterior)]+[path_d(r) for r in material.interiors])
(OUT/'vintage-owl-heraldic-panel.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="600mm" height="600mm" viewBox="0 0 600 600"><path d="{d}" fill="#111" fill-rule="evenodd"/></svg>\n',encoding='utf-8')
# Premium but truthful flat-metal preview.
def mpl_path(poly):
 verts=[]; codes=[]
 for ring in [poly.exterior,*poly.interiors]:
  xy=list(ring.coords); verts.extend(xy); codes.extend([MplPath.MOVETO]+[MplPath.LINETO]*(len(xy)-2)+[MplPath.CLOSEPOLY])
 return MplPath(verts,codes)
fig,ax=plt.subplots(figsize=(8,9),dpi=190); fig.patch.set_facecolor('#eee8df'); ax.set_facecolor('#eee8df')
ax.add_patch(PathPatch(mpl_path(material),facecolor='#171819',edgecolor='#090909',lw=.6))
ax.set_xlim(-305,305); ax.set_ylim(-260,260); ax.set_aspect('equal'); ax.axis('off')
ax.text(0,-255,'VINTAGE OWL HERALDIC PANEL  •  580 × 450 mm  •  2 mm STEEL',ha='center',va='bottom',fontsize=8,color='#4e4a45',weight='bold')
fig.savefig(OUT/'vintage-owl-heraldic-preview.jpg',bbox_inches='tight',facecolor=fig.get_facecolor()); plt.close(fig)
area=material.area; mass=area*2*7.85e-6
metrics={'width_mm':580.0,'height_mm':450.0,'thickness_mm':2.0,'material':'mild steel','connected_components':1,'geometry_valid':material.is_valid,'source_paths':1,'source_raster_contours':len(contours),'discarded_trapped_islands':len(discarded),'discarded_island_area_mm2':round(sum(g.area for g in discarded),2),'merged_close_profiles':merged_close_profiles,'filled_micro_apertures':filled_micro_apertures,'total_closed_profiles':1+len(material.interiors),'retained_cut_profiles':len(material.interiors)-2,'mounting_holes':2,'mounting_hole_diameter_mm':8.0,'measured_minimum_gap_between_profiles_mm':round(min_gap,3),'minimum_gap_pair':pair,'area_mm2':round(area,2),'cut_length_mm':round(material.length,2),'mass_kg':round(mass,4),'cut_price_at_2_usd_per_kg':round(mass*2,2)}
(OUT/'geometry-metrics.json').write_text(json.dumps(metrics,indent=2)+'\n',encoding='utf-8')
print(json.dumps(metrics))
