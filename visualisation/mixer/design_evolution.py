# state file generated using paraview version 6.2.0
import paraview

paraview.compatibility.major = 6
paraview.compatibility.minor = 2

#### import the simple module from the paraview
from paraview.simple import *
#### disable automatic camera reset on 'Show'
paraview.simple._DisableFirstRenderCameraReset()

if "data_directory" not in globals():
    raise RuntimeError(
        "data_directory is not defined. Please set the data_directory variable before running this script."
    )
if "forward_file" not in globals():
    forward_file = "forward_fields_0.vtkhdf"
if "design_file" not in globals():
    design_file = "design_0.vtkhdf"

# ----------------------------------------------------------------
# setup views used in the visualization
# ----------------------------------------------------------------

# Create a new 'Render View'
renderView1 = CreateView('RenderView')
renderView1.Set(
    ViewSize=[1857, 782],
    AxesGrid='Grid Axes 3D Actor',
    OrientationAxesVisibility=0,
    CenterOfRotation=[2.0, 0.5, 0.5],
    CameraPosition=[
        -1.9618733122078622, 1.5781756002322753, 5.509845549477533
    ],
    CameraFocalPoint=[
        2.8009413570890658, -0.0204358346537689, -0.966029097427043
    ],
    CameraViewUp=[
        0.11333016892331155, 0.980790710365838, -0.15876351996566657
    ],
    CameraViewAngle=14.691478942213518,
)

SetActiveView(None)

# ----------------------------------------------------------------
# setup view layouts
# ----------------------------------------------------------------

# create new layout object 'Layout #2'
layout2 = CreateLayout(name='Layout #2')
layout2.AssignView(0, renderView1)
layout2.SetSize(1857, 782)

# ----------------------------------------------------------------
# restore active view
SetActiveView(renderView1)
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# setup the data processing pipelines
# ----------------------------------------------------------------

# create a new 'VTKHDF Reader'
forward_fields_0vtkhdf = VTKHDFReader(registrationName='Forward Fields',
                                      FileName=[data_directory + forward_file])
forward_fields_0vtkhdf.PointArrayStatus = ['Pressure', 'Velocity', 's']

# create a new 'Merge Blocks'
mergeBlocks2 = MergeBlocks(registrationName='MergeBlocks2',
                           Input=forward_fields_0vtkhdf)

# create a new 'Slice'
slice1 = Slice(registrationName='Slice1', Input=mergeBlocks2)
slice1.Set(
    SliceType='Plane',
    Crinkleslice=1,
    PointMergeMethod='Not Merging Points',
)

# init the 'Plane' selected for 'SliceType'
slice1.SliceType.Origin = [0.001, 0.5, 0.5]

# init the 'Plane' selected for 'HyperTreeGridSlicer'
slice1.HyperTreeGridSlicer.Origin = [2.0, 0.5, 0.5]

# create a new 'VTKHDF Reader'
design_0vtkhdf = VTKHDFReader(registrationName='Design',
                              FileName=[data_directory + design_file])
design_0vtkhdf.PointArrayStatus = [
    'PDE_filter_mapping', 'brinkman_amplitude', 'design_indicator'
]

# create a new 'Merge Blocks'
mergeBlocks1 = MergeBlocks(registrationName='MergeBlocks1',
                           Input=design_0vtkhdf)

# create a new 'VTKm Clip'
vTKmClip1 = VTKmClip(registrationName='VTKmClip1', Input=mergeBlocks1)
vTKmClip1.Set(
    Scalars=['POINTS', 'PDE_filter_mapping'],
    ClipValue=0.001,
)

# create a new 'VTKm Contour'
vTKmContour1 = VTKmContour(registrationName='VTKmContour1', Input=vTKmClip1)
vTKmContour1.Set(
    ContourBy=['POINTS', 'PDE_filter_mapping'],
    Isosurfaces=[0.9],
)

# create a new 'Smooth'
smooth1 = Smooth(registrationName='Smooth1', Input=vTKmContour1)
smooth1.Convergence = 0.0001

# create a new 'Clip Closed Surface'
clipClosedSurface1 = ClipClosedSurface(registrationName='ClipClosedSurface1',
                                       Input=smooth1)
clipClosedSurface1.ClippingPlane = 'Plane'

# init the 'Plane' selected for 'ClippingPlane'
clipClosedSurface1.ClippingPlane.Normal = [0.0, 1.0, 0.0]

# create a new 'Clip Closed Surface'
clipClosedSurface2 = ClipClosedSurface(registrationName='ClipClosedSurface2',
                                       Input=clipClosedSurface1)
clipClosedSurface2.ClippingPlane = 'Plane'

# init the 'Plane' selected for 'ClippingPlane'
clipClosedSurface2.ClippingPlane.Set(
    Origin=[0.0, 0.0, 1.0],
    Normal=[0.0, 0.0, -1.0],
)

# create a new 'Slice'
slice2 = Slice(registrationName='Slice2', Input=mergeBlocks2)
slice2.Set(
    SliceType='Plane',
    Crinkleslice=1,
    PointMergeMethod='Not Merging Points',
)

# init the 'Plane' selected for 'SliceType'
slice2.SliceType.Origin = [3.999999, 0.5, 0.5]

# init the 'Plane' selected for 'HyperTreeGridSlicer'
slice2.HyperTreeGridSlicer.Origin = [2.0, 0.5, 0.5]

# ----------------------------------------------------------------
# setup the visualization in view 'renderView1'
# ----------------------------------------------------------------

# show data from mergeBlocks1
mergeBlocks1Display = Show(mergeBlocks1, renderView1,
                           'UnstructuredGridRepresentation')

# trace defaults for the display properties.
mergeBlocks1Display.Set(
    Representation='Outline',
    ColorArrayName=[None, ''],
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
mergeBlocks1Display.ScaleTransferFunction.Points = [
    -1.5584799753888892e-14, 0.0, 0.5, 0.0, 0.9591442346572876, 1.0, 0.5, 0.0
]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
mergeBlocks1Display.OpacityTransferFunction.Points = [
    -1.5584799753888892e-14, 0.0, 0.5, 0.0, 0.9591442346572876, 1.0, 0.5, 0.0
]

# show data from vTKmClip1
vTKmClip1Display = Show(vTKmClip1, renderView1,
                        'UnstructuredGridRepresentation')

# get color transfer function/color map for 'PDE_filter_mapping'
pDE_filter_mappingLUT = GetColorTransferFunction('PDE_filter_mapping')
pDE_filter_mappingLUT.Set(
    AutomaticRescaleRangeMode='Never',
    RGBPoints=GenerateRGBPoints(preset_name='Grayscale', ),
    ColorSpace='RGB',
    NanColor=[1.0, 0.0, 0.0],
    Discretize=0,
    ScalarRangeInitialized=1.0,
)

# get opacity transfer function/opacity map for 'PDE_filter_mapping'
pDE_filter_mappingPWF = GetOpacityTransferFunction('PDE_filter_mapping')
pDE_filter_mappingPWF.Set(
    Points=[
        0.0, 0.0, 0.5, 0.0, 0.01, 0.1, 0.5, 0.0, 0.8, 0.3, 0.5, 0.0, 0.85, 0.4,
        0.5, 0.0, 0.89, 0.6, 0.5, 0.0, 0.900293231010437, 0.6875000596046448,
        0.5, 0.0, 0.929618775844574, 1.0, 0.5, 0.0, 1.0, 1.0, 0.5, 0.0
    ],
    ScalarRangeInitialized=1,
)

# trace defaults for the display properties.
vTKmClip1Display.Set(
    Representation='Volume',
    ColorArrayName=['POINTS', 'PDE_filter_mapping'],
    LookupTable=pDE_filter_mappingLUT,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
    ScalarOpacityFunction=pDE_filter_mappingPWF,
    ScalarOpacityUnitDistance=0.08,
    SelectMapper='Resample To Image',
    SamplingDimensions=[512, 512, 512],
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
vTKmClip1Display.ScaleTransferFunction.Points = [
    0.0010000000474974513, 0.0, 0.5, 0.0, 0.9636493921279907, 1.0, 0.5, 0.0
]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
vTKmClip1Display.OpacityTransferFunction.Points = [
    0.0010000000474974513, 0.0, 0.5, 0.0, 0.9636493921279907, 1.0, 0.5, 0.0
]

# show data from clipClosedSurface2
clipClosedSurface2Display = Show(clipClosedSurface2, renderView1,
                                 'GeometryRepresentation')

# trace defaults for the display properties.
clipClosedSurface2Display.Set(
    Representation='Surface',
    ColorArrayName=[None, ''],
    ComputePointNormals=1,
    FeatureAngle=45.0,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# show data from slice1
slice1Display = Show(slice1, renderView1, 'UnstructuredGridRepresentation')

# get color transfer function/color map for 's'
sLUT = GetColorTransferFunction('s')
sLUT.Set(
    AutomaticRescaleRangeMode='Never',
    RGBPoints=[
        # scalar, red, green, blue
        0.0,
        0.0,
        0.0,
        0.2,
        0.25,
        0.0,
        0.0,
        0.5,
        0.475,
        0.0,
        0.8,
        0.8,
        0.5,
        1.0,
        1.0,
        1.0,
        0.525,
        0.8,
        0.8,
        0.0,
        0.75,
        0.5,
        0.0,
        0.0,
        1.0,
        0.2,
        0.0,
        0.0,
    ],
    ColorSpace='RGB',
    Discretize=0,
    ScalarRangeInitialized=1.0,
)

# trace defaults for the display properties.
slice1Display.Set(
    Representation='Surface With Edges',
    ColorArrayName=['POINTS', 's'],
    LookupTable=sLUT,
    LineWidth=2.0,
    DisableLighting=1,
    EdgeColor=[1.0, 1.0, 1.0],
    EdgeOpacity=0.5,
    NonlinearSubdivisionLevel=2,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
slice1Display.ScaleTransferFunction.Points = [
    1.4744746685028076, 0.0, 0.5, 0.0, 1.5499392747879028, 1.0, 0.5, 0.0
]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
slice1Display.OpacityTransferFunction.Points = [
    1.4744746685028076, 0.0, 0.5, 0.0, 1.5499392747879028, 1.0, 0.5, 0.0
]

# show data from slice2
slice2Display = Show(slice2, renderView1, 'UnstructuredGridRepresentation')

# trace defaults for the display properties.
slice2Display.Set(
    Representation='Surface With Edges',
    ColorArrayName=['POINTS', 's'],
    LookupTable=sLUT,
    LineWidth=2.0,
    DisableLighting=1,
    EdgeColor=[1.0, 1.0, 1.0],
    EdgeOpacity=0.5,
    NonlinearSubdivisionLevel=2,
    DataAxesGrid='Grid Axes Representation',
    PolarAxes='Polar Axes Representation',
)

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
slice2Display.ScaleTransferFunction.Points = [
    -0.0018525671912357211, 0.0, 0.5, 0.0, 0.018464360386133194, 1.0, 0.5, 0.0
]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
slice2Display.OpacityTransferFunction.Points = [
    -0.0018525671912357211, 0.0, 0.5, 0.0, 0.018464360386133194, 1.0, 0.5, 0.0
]

# setup the color legend parameters for each legend in this view

# get color legend/bar for pDE_filter_mappingLUT in view renderView1
pDE_filter_mappingLUTColorBar = GetScalarBar(pDE_filter_mappingLUT,
                                             renderView1)
pDE_filter_mappingLUTColorBar.Set(
    AutoOrient=0,
    Orientation='Horizontal',
    WindowLocation='Any Location',
    Position=[0.75, 0.02],
    Title='Design',
    ComponentTitle='',
    TitleFontSize=24,
    ScalarBarThickness=20,
    ScalarBarLength=0.2,
    DrawTickMarks=0,
    DrawTickLabels=0,
    AddRangeLabels=0,
    AllowOverlappingLabels=1,
    DrawAnnotations=0,
)

# set color bar visibility
pDE_filter_mappingLUTColorBar.Visibility = 1

# get color legend/bar for sLUT in view renderView1
sLUTColorBar = GetScalarBar(sLUT, renderView1)
sLUTColorBar.Set(
    AutoOrient=0,
    Orientation='Horizontal',
    WindowLocation='Any Location',
    Position=[0.75, 0.1],
    Title='Scalar',
    ComponentTitle='',
    TitleFontSize=24,
    ScalarBarThickness=20,
    ScalarBarLength=0.2,
    DrawTickMarks=0,
    DrawTickLabels=0,
    AddRangeLabels=0,
    AllowOverlappingLabels=1,
    DrawAnnotations=0,
)

# set color bar visibility
sLUTColorBar.Visibility = 1

# show color legend
vTKmClip1Display.SetScalarBarVisibility(renderView1, True)

# show color legend
slice1Display.SetScalarBarVisibility(renderView1, True)

# show color legend
slice2Display.SetScalarBarVisibility(renderView1, True)

# ----------------------------------------------------------------
# setup color maps and opacity maps used in the visualization
# note: the Get..() functions create a new object, if needed
# ----------------------------------------------------------------

# get opacity transfer function/opacity map for 's'
sPWF = GetOpacityTransferFunction('s')
sPWF.ScalarRangeInitialized = 1

# ----------------------------------------------------------------
# setup animation scene, tracks and keyframes
# note: the Get..() functions create a new object, if needed
# ----------------------------------------------------------------

# get time animation track
timeAnimationCue1 = GetTimeTrack()

# initialize the animation scene

# get the time-keeper
timeKeeper1 = GetTimeKeeper()

# initialize the timekeeper

# initialize the animation track

# get animation scene
animationScene1 = GetAnimationScene()

# initialize the animation scene
animationScene1.Set(
    ViewModules=renderView1,
    Cues=timeAnimationCue1,
    AnimationTime=150.0,
    EndTime=25.0,
    PlayMode='Snap To TimeSteps',
)

# ----------------------------------------------------------------
# restore active source
SetActiveSource(None)
# ----------------------------------------------------------------

# ----------------------------------------------------------------
# setup camera links
# ----------------------------------------------------------------

##--------------------------------------------
## You may need to add some code at the end of this python script depending on your usage, eg:
#
## Render all views to see them appears
# RenderAllViews()
#
## Interact with the view, usefull when running from pvpython
# Interact()
#
## Save a screenshot of the active view
# SaveScreenshot("path/to/screenshot.png")
#
## Save a screenshot of a layout (multiple splitted view)
# SaveScreenshot("path/to/screenshot.png", GetLayout())
#
## Save all "Extractors" from the pipeline browser
# SaveExtracts()
#
## Save a animation of the current active view
# SaveAnimation()
#
## Please refer to the documentation of paraview.simple
## https://www.paraview.org/paraview-docs/nightly/python/
##--------------------------------------------
