import matplotlib.pyplot as plt
import numpy as np
from dolfinx_materials.quadrature_map import QuadratureMap
from dolfinx_materials.solvers import NonlinearMaterialProblem

import ufl
from dolfinx import fem, io, mesh
from dolfinx.cpp.nls.petsc import NewtonSolver

from mpi4py import MPI
from petsc4py import PETSc


def uniaxial_tension_2D(material, Exx, N=1, order=1, save_fields=None):
    domain = mesh.create_unit_square(MPI.COMM_WORLD, N, N, mesh.CellType.quadrilateral)
    V = fem.VectorFunctionSpace(domain, ("CG", order))

    deg_quad = 2 * (order - 1)

    def bottom(x):
        return np.isclose(x[1], 0)

    def left(x):
        return np.isclose(x[0], 0)

    def right(x):
        return np.isclose(x[0], 1.0)

    V_ux, mapping = V.sub(0).collapse()
    left_dofs_ux = fem.locate_dofs_geometrical((V.sub(0), V_ux), left)
    right_dofs_ux = fem.locate_dofs_geometrical((V.sub(0), V_ux), right)
    V_uy, mapping = V.sub(1).collapse()
    bottom_dofs_uy = fem.locate_dofs_geometrical((V.sub(1), V_uy), bottom)

    uD_x = fem.Function(V_ux)
    uD_y = fem.Function(V_uy)
    uD_x_r = fem.Function(V_ux)
    bcs = [
        fem.dirichletbc(uD_x, left_dofs_ux, V.sub(0)),
        fem.dirichletbc(uD_y, bottom_dofs_uy, V.sub(1)),
        fem.dirichletbc(uD_x_r, right_dofs_ux, V.sub(0)),
    ]

    du = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    u = fem.Function(V)

    def strain(u):
        return ufl.as_vector(
            [
                u[0].dx(0),
                u[1].dx(1),
                0.0,
                1 / np.sqrt(2) * (u[1].dx(0) + u[0].dx(1)),
                0.0,
                0.0,
            ]
        )

    qmap = QuadratureMap(domain, deg_quad, material)
    qmap.register_gradient(material.gradient_names[0], strain(u))

    sig = qmap.fluxes[material.flux_names[0]]
    Res = ufl.dot(sig, strain(v)) * qmap.dx
    Jac = qmap.derivative(Res, u, du)

    problem = NonlinearMaterialProblem(qmap, Res, Jac, u, bcs)
    newton = NewtonSolver(MPI.COMM_WORLD)
    newton.rtol = 1e-6
    newton.max_it = 10

    file_results = io.XDMFFile(
        domain.comm,
        f"{material.name}_results.xdmf",
        "w",
    )
    file_results.write_mesh(domain)
    Stress = np.zeros((len(Exx), 6))
    for i, exx in enumerate(Exx[1:]):
        uD_x_r.vector.array[:] = exx

        converged, it = problem.solve(newton)

        assert converged
        Stress[i + 1, :] = sig.vector.array[:6]

        if save_fields is not None:
            for field_name in save_fields:
                field = qmap.project_on(field_name, ("DG", 0))
                file_results.write_function(field, i)

    # plt.figure()
    # plt.plot(Exx, Stress[:, 0], "-o", label=r"$\sigma_{xx}$")
    # plt.plot(Exx, Stress[:, 1], "-o", label=r"$\sigma_{yy}$")
    # plt.plot(Exx, Stress[:, 2], "-o", label=r"$\sigma_{zz}$")
    # plt.xlabel(r"Strain $\varepsilon_{xx}$")
    # plt.ylabel(r"Stress")
    # plt.legend()
    # plt.savefig(f"{material.name}_stress_strain.pdf")

    file_results.close()
    return Stress
